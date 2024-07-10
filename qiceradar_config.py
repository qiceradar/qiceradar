import pathlib
from typing import Dict, NamedTuple, Optional

import requests


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


def rootdir_is_valid(config: UserConfig) -> bool:
    return config.rootdir is not None and config.rootdir.is_dir()

def nsidc_token_is_valid(config: UserConfig) -> bool:
    test_url = "https://n5eil01u.ecs.nsidc.org/ICEBRIDGE/IR1HI1B.001/2009.01.02/IR1HI1B_2009002_MCM_JKB1a_DGC02a_000.nc"
    headers = {"Authorization": f"Bearer {config.nsidc_token}"}
    try:
        req = requests.get(test_url, stream=True, headers=headers)
    except:
        # We expect this to fail if there's no valid internet connection.
        return False
    return req.status_code == 200

