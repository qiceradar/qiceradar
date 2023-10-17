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
        filepath = pathlib.Path(rootdir, region, institution, campaign, segment)
        # filepath = pathlib.Path(rootdir, region, institution, campaign, segment + ".nc")
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
