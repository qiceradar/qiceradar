import pathlib
from typing import Dict, NamedTuple, Optional


class UserConfig(NamedTuple):
    rootdir: Optional[pathlib.Path] = None
    nsidc_token: Optional[str] = None
    aad_access_key: Optional[str] = None
    aad_secret_key: Optional[str] = None


def parse_config(config_dict: Dict[str, str]) -> UserConfig:
    rootdir = None
    nsidc_token = None
    aad_access_key = None
    aad_secret_key = None
    if "rootdir" in config_dict:
        pp = pathlib.Path(config_dict["rootdir"])
        if pp.is_dir():
            rootdir = pp
    if "nsidc_token" in config_dict:
        nsidc_token = config_dict["nsidc_token"]
    if "aad_access_key" in config_dict:
        aad_access_key = config_dict["aad_access_key"]
    if "aad_secret_key" in config_dict:
        aad_secret_key = config_dict["aad_secret_key"]

    config = UserConfig(
        rootdir, nsidc_token, aad_access_key, aad_secret_key
    )
    return config


def config_is_valid(config: UserConfig) -> bool:
    return config.rootdir is not None and config.rootdir.is_dir()
