# Copyright 2022-2024 Laura Lindzey, UW-APL
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# “AS IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


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

