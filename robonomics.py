"""This module contain methods to communicate with Robonomics blockchain"""

import asyncio
import logging

from robonomicsinterface import (
    Account,
    Datalog,
)
from substrateinterface import KeypairType
from tenacity import Retrying, stop_after_attempt, wait_fixed

from homeassistant.core import HomeAssistant

import typing as tp

from .const import (
    CONF_POLKADOT,
    ROBONOMICS_WSS_KUSAMA,
    ROBONOMICS_WSS_POLKADOT,
)

_LOGGER = logging.getLogger(__name__)


class Robonomics:
    """Represents methods to interact with Robonomics parachain"""

    def __init__(
        self,
        hass: HomeAssistant,
        sub_owner_address: str,
        controller_seed: str,
        controller_type: KeypairType | None,
        network: str,
    ) -> None:
        self.controller_type: KeypairType = controller_type if controller_type else KeypairType.ED25519
        self.robonomics_ws_list = ROBONOMICS_WSS_POLKADOT if network == CONF_POLKADOT else ROBONOMICS_WSS_KUSAMA
        self.current_wss = self.robonomics_ws_list[0]
        _LOGGER.debug(f"Use endpoint {self.current_wss}")
        self.hass: HomeAssistant = hass
        self.sub_owner_address: str = sub_owner_address
        self.controller_seed: str = controller_seed
        self.controller_account: Account = Account(
            seed=self.controller_seed,
            crypto_type=self.controller_type,
            remote_ws=self.current_wss,
        )
        self.controller_address: str = self.controller_account.get_address()
        self.sending_states: bool = False
        self.sending_creds: bool = False
        self.on_queue: int = 0
        self.last_datalog: tp.Optional[str] = None


    def _change_current_wss(self) -> None:
        """Set next current wss"""

        current_index = self.robonomics_ws_list.index(self.current_wss)
        if current_index == (len(self.robonomics_ws_list) - 1):
            next_index = 0
        else:
            next_index = current_index + 1
        self.current_wss = self.robonomics_ws_list[next_index]
        _LOGGER.debug(f"New Robonomics ws is {self.current_wss}")
        self.controller_account: Account = Account(
            seed=self.controller_seed,
            crypto_type=self.controller_type,
            remote_ws=self.current_wss,
        )

    async def get_last_datalog(self) -> None:
        self.last_datalog = await self.hass.async_add_executor_job(self._get_last_datalog)

    def _get_last_datalog(self) -> tp.Optional[str]:
        """Getting the last hash with telemetry from Datalog.

        :return: Last IPFS hash if success, None otherwise
        """

        try:
            for attempt in Retrying(
                wait=wait_fixed(2), stop=stop_after_attempt(len(self.robonomics_ws_list))
            ):
                with attempt:
                    try:
                        datalog = Datalog(Account(remote_ws=self.current_wss))
                        last_hash = datalog.get_item(self.controller_address)
                    except TimeoutError:
                        self._change_current_wss()
                        raise TimeoutError
            _LOGGER.debug(f"Got last hash from datalog: {last_hash}")
            if last_hash[1][:2] != "Qm":
                return None
            else:
                return last_hash[1]

        except Exception as e:
            _LOGGER.debug(f"Exception in getting last telemetry hash: {e}")

    def _send_datalog(self, data: str) -> str:
        """Record datalog

        :param data: Data for Datalog recors

        :return: Exstrinsic hash
        """
        self.last_datalog = data
        for attempt in Retrying(
            wait=wait_fixed(2), stop=stop_after_attempt(3)
        ):
            with attempt:
                try:
                    _LOGGER.debug("Start creating rws datalog")
                    datalog = Datalog(self.controller_account, rws_sub_owner=self.sub_owner_address)
                    receipt = datalog.record(data)
                except TimeoutError:
                    self._change_current_wss()
                    raise TimeoutError
                except Exception as e:
                    _LOGGER.warning(f"Datalog sending exeption: {e}")
                    return None
        _LOGGER.debug(f"Datalog created with hash: {receipt}")
        return receipt

    async def send_datalog_with_queue(self, data: str) -> str:
        _LOGGER.debug(
            f"Send datalog request, another datalog: {self.sending_states}"
        )
        if self.sending_states:
            _LOGGER.debug("Another datalog is sending. Wait...")
            self.on_queue += 1
            on_queue = self.on_queue
            wait_count = 0
            while self.sending_states:
                await asyncio.sleep(5)
                if on_queue < self.on_queue:
                    _LOGGER.debug("Stop waiting to send datalog")
                    return
                if wait_count > 12:
                    break
                wait_count += 1
            self.sending_states = True
            self.on_queue = 0
            await asyncio.sleep(10)
        else:
            self.sending_states = True
            self.on_queue = 0
        receipt = await self.hass.async_add_executor_job(self._send_datalog, data)
        self.sending_states = False
        return receipt


