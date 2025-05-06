"""File with functions for Home Assistant services"""

import asyncio
import logging
import os
import tempfile
import time
import typing as tp
from pathlib import Path
import cv2
from PIL import Image
import numpy as np
import io
import random


from homeassistant.components.camera.const import DOMAIN as CAMERA_DOMAIN
from homeassistant.components.camera.const import SERVICE_RECORD
from homeassistant.components.camera import SERVICE_SNAPSHOT
from homeassistant.core import HomeAssistant, ServiceCall
from robonomicsinterface import Account
from substrateinterface import Keypair, KeypairType

from .const import (
    DOMAIN,
    IPFS_MEDIA_PATH,
    ROBONOMICS,
    TWIN_ID,
    IPFS_MEDIA_META_FILE
)
from .ipfs import add_media_to_ipfs
from .utils import encrypt_message, FileSystemUtils
from .ipfs_helpers.utils import IPFSLocalUtils
from .robonomics import Robonomics

_LOGGER = logging.getLogger(__name__)


async def save_video(
    hass: HomeAssistant,
    target: tp.Dict[str, str],
    path: str,
    duration: int,
    sub_admin_acc: Account,
) -> None:
    """Record a video with given duration, save it in IPFS and Digital Twin

    :param hass: Home Assistant instance
    :param target: What should this service use as targeted areas, devices or entities. Usually it's camera entity ID.
    :param path: Path to save the video (must be also in configuration.yaml)
    :param duration: Duration of the recording in seconds
    :param sub_admin_acc: Controller account address
    """

    if path[-1] == "/":
        path = path[:-1]
    filename = f"video-{int(time.time())}.mp4"
    data = {"duration": duration, "filename": f"{path}/{filename}"}
    _LOGGER.debug(f"Started recording video {path}/{filename} for {duration} seconds")
    await hass.services.async_call(
        domain=CAMERA_DOMAIN,
        service=SERVICE_RECORD,
        service_data=data,
        target=target,
        blocking=True,
    )
    count = 0
    while not os.path.isfile(f"{path}/{filename}"):
        await asyncio.sleep(2)
        count += 1
        if count > 10:
            break
    if os.path.isfile(f"{path}/{filename}"):
        _LOGGER.debug(f"Start encrypt video {filename}")
        admin_keypair: Keypair = sub_admin_acc.keypair
        video_data = await FileSystemUtils(hass).read_file_data(f"{path}/{filename}", "rb")
        encrypted_data = encrypt_message(
            video_data, admin_keypair, admin_keypair.public_key
        )
        await FileSystemUtils(hass).write_file_data(f"{path}/{filename}", encrypted_data)
        meta_ipfs_hash = await add_media_to_ipfs(hass, f"{path}/{filename}")
        # delete file from system
        _LOGGER.debug(f"delete original video {filename}")
        await FileSystemUtils(hass).delete_temp_file(f"{path}/{filename}")
        await hass.data[DOMAIN][ROBONOMICS].set_media_topic(
            meta_ipfs_hash, hass.data[DOMAIN][TWIN_ID]
        )

async def save_photo(
    hass: HomeAssistant,
    target: tp.Dict[str, str],
    path: str,
    use_emoji: bool,
) -> None:
    """make a photo, save it in IPFS and Digital Twin

    :param hass: Home Assistant instance
    :param target: What should this service use as targeted areas, devices or entities. Usually it's camera entity ID.
    :param path: Path to save the photo (must be also in configuration.yaml)
    :param sub_admin_acc: Controller account address
    """

    if path[-1] == "/":
        path = path[:-1]
    filename = f"photo-{int(time.time())}.jpg"
    data = {"filename": f"{path}/{filename}"}
    _LOGGER.debug(f"Started making photo {path}/{filename} ")
    await hass.services.async_call(
        domain=CAMERA_DOMAIN,
        service=SERVICE_SNAPSHOT,
        service_data=data,
        target=target,
        blocking=True,
    )
    count = 0
    while not os.path.isfile(f"{path}/{filename}"):
        await asyncio.sleep(2)
        count += 1
        if count > 10:
            break
    if os.path.isfile(f"{path}/{filename}"):
        #_LOGGER.debug(f"Start encrypt video {filename}")
        if use_emoji:
            input_photo = await FileSystemUtils(hass).read_file_data(f"{path}/{filename}", "rb")
            np_arr = np.frombuffer(input_photo, np.uint8)
            cv_image = cv2.imdecode(np_arr, cv2.IMREAD_UNCHANGED)
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            image = Image.fromarray(cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB))



            # Классификатор лиц OpenCV
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)

            # Накладываем смайлик на каждое лицо
            for (x, y, w, h) in faces:
                emoji_num = random.randint(1, 17)
                emoji_bin = await FileSystemUtils(hass).read_file_data(
                    f"/home/homeassistant/.homeassistant/media/smiles/{emoji_num}.png", "rb")
                emoji = Image.open(io.BytesIO(emoji_bin)).convert("RGBA")
                resized_emoji = emoji.resize((w, h))
                image.paste(resized_emoji, (x, y), resized_emoji)

            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG")  # или PNG, если нужна прозрачность
            buffer.seek(0)

            image_bytes = buffer.read()
            await FileSystemUtils(hass).write_file_data(f"{path}/{filename}", image_bytes, "wb")
        hass.create_task(add_media_to_ipfs(hass, f"{path}/{filename}"))

async def send_media_folder_if_changed(hass: HomeAssistant) -> None:
    """Check if media folder has changed and send it to IPFS and Digital Twin

    :param hass: Home Assistant instance
    """
    robonomics: Robonomics = hass.data[DOMAIN][ROBONOMICS]
    meta_ipfs_hash = await IPFSLocalUtils(hass).get_folder_or_file_hash(f"{IPFS_MEDIA_PATH}/{IPFS_MEDIA_META_FILE}")
    if meta_ipfs_hash != robonomics.last_datalog:
        _LOGGER.debug(f"Media meta file {IPFS_MEDIA_PATH}/{IPFS_MEDIA_META_FILE} has been changed, sending to IPFS")
        await robonomics.send_datalog_with_queue(meta_ipfs_hash)