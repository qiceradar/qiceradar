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
from typing import Optional


# TODO: I need tests for this, constructing every filepath in the database
def get_granule_filepath(
    rootdir: pathlib.Path, region, institution, campaign, segment, granule
) -> Optional[pathlib.Path]:
    """
    While we'e shoved all transects into the same database fields,
    our attempt to download filestructures matching how the various
    providers organize their data means that we need provider- and
    even campaign-specific logic for handling them.
    """
    filepath = None
    if institution == "BAS":
        # Deliberately wrong to test the download widget
        # filepath = pathlib.Path(rootdir, region, institution, campaign, segment)
        filepath = pathlib.Path(rootdir, region, institution, campaign, segment + ".nc")
    elif institution == "CRESIS":
        # TODO: Should probably download from NSIDC where available...
        #   So maybe don't deal with these yet.
        pass
    elif institution == "KOPRI":
        # So far, only have KRT1 data.
        filepath = pathlib.Path(
            rootdir, region, institution, campaign, segment, granule + ".nc"
        )
    elif institution == "LDEO":
        # Only handle AGAP_GAMBIT; the ROSETTA samples I have are a mess
        if campaign == "AGAP_GAMBIT":
            # These are self-hosted, and I assume a totally differnt format from more recent data will be
            filepath = pathlib.Path(
                rootdir, region, institution, campaign, segment, granule + ".nc"
            )
    elif institution == "SOAR":
        # BEDMAP has these as UTIG; however, I found the radargrams at LDEO.
        # SO, keeping them a bit separate under the "SOAR" category for now.
        filepath = pathlib.Path(
            rootdir, region, institution, campaign, segment + ".segy"
        )
    elif institution == "UTIG":
        filepath = pathlib.Path(
            rootdir, region, institution, campaign, segment, granule + ".nc"
        )

    return filepath
