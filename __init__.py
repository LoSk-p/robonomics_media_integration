""""
Entry point for integration.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import logging
import os
import shutil
from collections.abc import Callable

from pinatapy import PinataPy
from homeassistant.util.hass_dict import HassKey

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, MATCH_ALL, EVENT_STATE_CHANGED
from homeassistant.core import (
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    ServiceCall,
    callback,
)
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

from .const import (
    CONF_ADMIN_SEED,
    CONF_IPFS_GATEWAY,
    CONF_IPFS_GATEWAY_AUTH,
    CONF_IPFS_GATEWAY_PORT,
    CONF_PINATA_PUB,
    CONF_PINATA_SECRET,
    CONF_SENDING_TIMEOUT,
    CONF_SUB_OWNER_ADDRESS,
    DATA_PATH,
    DOMAIN,
    HANDLE_IPFS_REQUEST,
    HANDLE_TIME_CHANGE,
    IPFS_STATUS,
    PINATA,
    PLATFORMS,
    ROBONOMICS,
    SAVE_VIDEO_SERVICE,
    SAVE_PHOTO_SERVICE,
    TIME_CHANGE_COUNT,
    TIME_CHANGE_UNSUB,
    TWIN_ID,
    GETTING_STATES_QUEUE,
    GETTING_STATES,
    IPFS_CONFIG_PATH,
    IPFS_DAEMON_OK,
    LIBP2P_UNSUB,
    IPFS_STATUS_ENTITY,
    IPFS_DAEMON_STATUS_STATE_CHANGE,
    HANDLE_LIBP2P_STATE_CHANGED,
    WAIT_IPFS_DAEMON,
    LIBP2P,
    HANDLE_TIME_CHANGE_LIBP2P,
    TIME_CHANGE_LIBP2P_UNSUB,
    CONTROLLER_ADDRESS,
    CONF_CONTROLLER_TYPE,
    TELEMETRY_SENDER,
    CONF_NETWORK,
)
from .ipfs import (
    create_folders,
    wait_ipfs_daemon,
    handle_ipfs_status_change,
)
from .ipfs_helpers.utils import IPFSLocalUtils
from .robonomics import Robonomics
from .services import (
    save_video,
    save_photo,
    send_media_folder_if_changed
)

DATA_BACKUP_AGENT_LISTENERS: HassKey[list[Callable[[], None]]] = HassKey(
    f"{DOMAIN}.backup_agent_listeners"
)


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update. It's called when config updates.

    :param hass: HomeAssistant instance
    :param entry: Data from config
    """
    try:
        _LOGGER.debug("Reconfigure Robonomics Integration")
        _LOGGER.debug(f"HASS.data before: {hass.data[DOMAIN]}")
        _LOGGER.debug(f"entry options before: {entry.options}")
        hass.data[DOMAIN][CONF_SENDING_TIMEOUT] = timedelta(
            minutes=entry.options[CONF_SENDING_TIMEOUT]
        )
        hass.data[DOMAIN][CONF_PINATA_PUB] = entry.options[CONF_PINATA_PUB]
        hass.data[DOMAIN][CONF_PINATA_SECRET] = entry.options[CONF_PINATA_SECRET]
        hass.data[DOMAIN][TELEMETRY_SENDER].setup(hass.data[DOMAIN][CONF_SENDING_TIMEOUT])
        hass.data[DOMAIN][TIME_CHANGE_UNSUB]()
        hass.data[DOMAIN][TIME_CHANGE_UNSUB] = async_track_time_interval(
            hass,
            hass.data[DOMAIN][HANDLE_TIME_CHANGE],
            hass.data[DOMAIN][CONF_SENDING_TIMEOUT],
        )
        _LOGGER.debug(f"HASS.data after: {hass.data[DOMAIN]}")
    except Exception as e:
        _LOGGER.error(f"Exception in update_listener: {e}")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Robonomics Integration from a config entry.
    It calls every time integration uploading and after config flow during initial
    setup.

    :param hass: HomeAssistant instance
    :param entry: Data from config

    :return: True after succesfull setting up

    """
    hass.data.setdefault(DOMAIN, {})
        

    _LOGGER.debug("Robonomics user control starting set up")
    conf = entry.data
    if CONF_IPFS_GATEWAY in conf:
        hass.data[DOMAIN][CONF_IPFS_GATEWAY] = conf[CONF_IPFS_GATEWAY]
    hass.data[DOMAIN][CONF_IPFS_GATEWAY_AUTH] = conf[CONF_IPFS_GATEWAY_AUTH]
    hass.data[DOMAIN][CONF_IPFS_GATEWAY_PORT] = conf[CONF_IPFS_GATEWAY_PORT]
    hass.data[DOMAIN][CONF_SENDING_TIMEOUT] = timedelta(
        minutes=conf[CONF_SENDING_TIMEOUT]
    )
    _LOGGER.debug(f"Sending interval: {conf[CONF_SENDING_TIMEOUT]} minutes")
    hass.data[DOMAIN][CONF_ADMIN_SEED] = conf[CONF_ADMIN_SEED]
    hass.data[DOMAIN][CONF_SUB_OWNER_ADDRESS] = conf[CONF_SUB_OWNER_ADDRESS]
    hass.data[DOMAIN][GETTING_STATES_QUEUE] = 0
    hass.data[DOMAIN][GETTING_STATES] = False
    hass.data[DOMAIN][IPFS_DAEMON_OK] = True
    hass.data[DOMAIN][WAIT_IPFS_DAEMON] = False

    robonomics: Robonomics = Robonomics(
        hass,
        hass.data[DOMAIN][CONF_SUB_OWNER_ADDRESS],
        hass.data[DOMAIN][CONF_ADMIN_SEED],
        conf.get(CONF_CONTROLLER_TYPE),
        conf.get(CONF_NETWORK)
    )
    hass.data[DOMAIN][ROBONOMICS] = robonomics

    async def init_integration(_: Event = None) -> None:
        """Compare rws devices with users from Home Assistant

        :param hass: HomeAssistant instance
        """
        await robonomics.get_last_datalog()

    controller_account = hass.data[DOMAIN][ROBONOMICS].controller_account

    hass.data[DOMAIN][CONTROLLER_ADDRESS] = robonomics.controller_address
    _LOGGER.debug(f"Controller: {hass.data[DOMAIN][CONTROLLER_ADDRESS]}")
    _LOGGER.debug(f"Owner: {hass.data[DOMAIN][CONF_SUB_OWNER_ADDRESS]}")
    hass.data[DOMAIN][CONF_PINATA_PUB] = conf[CONF_PINATA_PUB]
    hass.data[DOMAIN][CONF_PINATA_SECRET] = conf[CONF_PINATA_SECRET]
    hass.data[DOMAIN][IPFS_STATUS] = "OK"
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await wait_ipfs_daemon(hass, timeout = 30)
    try:
        await create_folders(hass)
    except Exception as e:
        _LOGGER.error(f"Exception in create ipfs folders: {e}")
        await wait_ipfs_daemon(hass, timeout = 30)
    hass.states.async_set(
        f"sensor.{IPFS_STATUS_ENTITY}", hass.data[DOMAIN][IPFS_STATUS]
    )

    hass.data[DOMAIN][HANDLE_IPFS_REQUEST] = False
    entry.async_on_unload(entry.add_update_listener(update_listener))

    hass.data[DOMAIN][TIME_CHANGE_COUNT] = 0

    @callback
    def handle_time_changed_callback(event):
        hass.loop.create_task(handle_time_changed(event))

    async def handle_time_changed(event):
        """Callback for time' changing subscription.
        It calls every timeout from config to get and send telemtry.

        :param event: Current date & time
        """

        try:
            await send_media_folder_if_changed(hass)
        except Exception as e:
            _LOGGER.error(f"Exception in handle_time_changed: {e}")

    hass.data[DOMAIN][HANDLE_TIME_CHANGE] = handle_time_changed_callback

    async def handle_save_video(call: ServiceCall) -> None:
        """Callback for save_video_to_robonomics service"""
        if "entity_id" in call.data:
            target = {"entity_id": call.data["entity_id"]}
        elif "device_id" in call.data:
            target = {"device_id": call.data["device_id"]}
        if "duration" in call.data:
            duration = call.data["duration"]
        else:
            duration = 10
        path = call.data["path"]
        await save_video(hass, target, path, duration, controller_account)

    hass.services.async_register(DOMAIN, SAVE_VIDEO_SERVICE, handle_save_video)

    async def handle_save_photo(call: ServiceCall) -> None:
        """Callback for save_video_to_robonomics service"""
        if "entity_id" in call.data:
            target = {"entity_id": call.data["entity_id"]}
        elif "device_id" in call.data:
            target = {"device_id": call.data["device_id"]}
        path = call.data["path"]
        use_emoji = call.data.get("use_emoji", True)
        await save_photo(hass, target, path, use_emoji, controller_account)

    hass.services.async_register(DOMAIN, SAVE_PHOTO_SERVICE, handle_save_photo)


    hass.data[DOMAIN][TIME_CHANGE_UNSUB] = async_track_time_interval(
        hass,
        hass.data[DOMAIN][HANDLE_TIME_CHANGE],
        hass.data[DOMAIN][CONF_SENDING_TIMEOUT],
    )

    if hass.state == CoreState.running:
        asyncio.ensure_future(init_integration())
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, init_integration)

    _LOGGER.debug(
        f"Robonomics user control successfuly set up, hass state: {hass.state}"
    )
    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    _LOGGER.debug(f"setup data: {config.get(DOMAIN)}")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.
    It calls during integration's removing.

    :param hass: HomeAssistant instance
    :param entry: Data from config

    :return: True when integration is unloaded
    """

    hass.data[DOMAIN][TELEMETRY_SENDER].unload()
    hass.data[DOMAIN][TIME_CHANGE_UNSUB]()
    hass.data[DOMAIN][TIME_CHANGE_LIBP2P_UNSUB]()
    await hass.data[DOMAIN][LIBP2P].close_connection()
    if LIBP2P_UNSUB in hass.data[DOMAIN]:
        hass.data[DOMAIN][LIBP2P_UNSUB]()
    hass.data[DOMAIN][ROBONOMICS].subscriber.cancel()
    await IPFSLocalUtils(hass).delete_folder(IPFS_CONFIG_PATH)
    hass.data.pop(DOMAIN)
    await asyncio.gather(
        *(
            hass.config_entries.async_forward_entry_unload(entry, component)
            for component in PLATFORMS
        )
    )
    _LOGGER.debug("Robonomics integration was unloaded")
    return True
