"""Config flow for Robonomics Control integration. It is service module for HomeAssistant,
which sets in `manifest.json`. This module allows to setup the integration from the web interface.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_ADMIN_SEED,
    CONF_PINATA_PUB,
    CONF_PINATA_SECRET,
    CONF_PINATA_USE,
    CONF_SENDING_TIMEOUT,
    CONF_SUB_OWNER_ADDRESS,
    CONF_NETWORK,
    CONF_KUSAMA,
    CONF_POLKADOT,
    DOMAIN,
)
from .config_flow_helpers import ConfigValidator

_LOGGER = logging.getLogger(__name__)


NETWORK_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[CONF_KUSAMA, CONF_POLKADOT],
        mode=SelectSelectorMode.DROPDOWN,
        translation_key="network",
    )
)

STEP_MANUAL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADMIN_SEED): str,
        vol.Required(CONF_SUB_OWNER_ADDRESS): str,
        vol.Required(CONF_NETWORK, default=CONF_POLKADOT): NETWORK_SELECTOR,
        vol.Required(CONF_PINATA_PUB): str,
        vol.Required(CONF_PINATA_SECRET): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Robonomics Control."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""

        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:

        errors = {}
        self.config = {}
        device_unique_id = "robonomics"
        await self.async_set_unique_id(device_unique_id)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_MANUAL_DATA_SCHEMA
            )
        errors = {}
        _LOGGER.debug(f"User data: {user_input}")
        self.config[CONF_SUB_OWNER_ADDRESS] = user_input[CONF_SUB_OWNER_ADDRESS]
        self.config[CONF_NETWORK] = user_input[CONF_NETWORK]
        self.config[CONF_PINATA_PUB] = user_input[CONF_PINATA_PUB]
        self.config[CONF_PINATA_SECRET] = user_input[CONF_PINATA_SECRET]
        self.config[CONF_SENDING_TIMEOUT] = 1
        try:
            self.config[CONF_ADMIN_SEED] = ConfigValidator.get_raw_seed_from_config(user_input[CONF_ADMIN_SEED])
        except Exception as e:
            _LOGGER.error(f"Exception in seed parsing: {e}")
            return self.async_show_form(
                step_id="user", data_schema=STEP_MANUAL_DATA_SCHEMA, errors={"base": "invalid_sub_admin_seed"}
            )
        try:
            await ConfigValidator(self.hass, self.config).validate()
        except Exception as e:
            errors["base"] = ConfigValidator.get_error_key(e)
        else:
            return self.async_create_entry(title="Robonomics Media", data=self.config)

        return self.async_show_form(
            step_id="user", data_schema=STEP_MANUAL_DATA_SCHEMA, errors=errors
        )
            


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialise options flow. THis class contains methods to manage config after it was initialised."""

        self.config_entry = config_entry
        _LOGGER.debug(config_entry.data)
        self.updated_config = self.config_entry.data.copy()
        _LOGGER.debug(f"Updated config: {self.updated_config}")

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage Timeout and Pinata and Custom IPFS gateways.

        :param user_input: Dict with the keys from OPTIONS_DATA_SCHEMA and values provided by user

        :return: Service functions from HomeAssistant
        """

        if user_input is not None:
            _LOGGER.debug(f"User input: {user_input}")
            if not user_input[CONF_PINATA_USE]:
                user_input.pop(CONF_PINATA_PUB, None)
                user_input.pop(CONF_PINATA_SECRET, None)
                self.updated_config.pop(CONF_PINATA_PUB, None)
                self.updated_config.pop(CONF_PINATA_SECRET, None)
            del user_input[CONF_PINATA_USE]
     
            self.updated_config.update(user_input)

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=self.updated_config
            )
            return self.async_create_entry(title="", data=user_input)

        if CONF_PINATA_PUB in self.config_entry.data:
            pinata_pub = self.config_entry.data[CONF_PINATA_PUB]
            pinata_secret = self.config_entry.data[CONF_PINATA_SECRET]
            OPTIONS_DATA_SCHEMA = vol.Schema(
                {
                    vol.Required(
                        CONF_SENDING_TIMEOUT,
                        default=self.config_entry.data[CONF_SENDING_TIMEOUT],
                    ): int,
                    vol.Required(CONF_PINATA_USE, default=True): bool,
                    vol.Optional(CONF_PINATA_PUB, default=pinata_pub): str,
                    vol.Optional(CONF_PINATA_SECRET, default=pinata_secret): str,
                }
            )
        else:
            OPTIONS_DATA_SCHEMA = vol.Schema(
                {
                    vol.Required(
                        CONF_SENDING_TIMEOUT,
                        default=self.config_entry.data[CONF_SENDING_TIMEOUT],
                    ): int,
                    vol.Required(CONF_PINATA_USE, default=False): bool,
                    vol.Optional(CONF_PINATA_PUB): str,
                    vol.Optional(CONF_PINATA_SECRET): str,
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=OPTIONS_DATA_SCHEMA,
            last_step=False,
        )
