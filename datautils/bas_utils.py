import netCDF4 as nc
import numpy as np

# All institution-specific Radargram classes will need to have
# * get_track: returns lat, lon arrays
# * get_trace_times: returns posix time for each trace in radargram
# * get_sample_times: returns time-since-transmission, in us, for each row in radargram
# * .data[::row_skip,::col_skip]
# * set_product(product); since BAS radargrams don't have consistent diensions across products, any caller instantiating this class ALWAYS need to call the above accessors, rather than caching their output.


# For now, just using duck typing for the institution-specific radargram classes
class BasRadargram:
    def __init__(self, filepath):
        pass


def load_chirp_data(filepath: str):
    dd = nc.Dataset(filepath, "r")

    # NOTE: I'm torn on whether to use campaign vs. data fields to make this decision.
    #    I wound up choosing campaign since the presence of PriNumber isn't a good signal
    #    as to which direction interpolation needs to go: FISS2016 uses them for segy, but
    #    in netCDF pulse/chirp are same length with the traces aligned; AGAP has picks
    #    indexed to traces_pulse, and POLARGAP has picks indexed to traces_chirp.
    #    (I guess I could check based on length...)
    #    However, this means that adding new campaigns may require editing code, even if
    #    they're consistent with a previous campaign's format.
    if dd.campaign == "IMAFI":
        # The IMAFI season had two different versions of the chirp product: cHG, DLRsar
        # For now, arbitrarily picking cHG
        chirp_data = dd.variables["chirp_cHG_data"][:].data.transpose()
    elif dd.campaign == "POLARGAP":
        # TODO: add support switching between these products?
        # The POLARGAP season had polarised_chirp_{PPVV,SSHH}_data
        # (and polarised_pulse_data) for flights 1-23. After that, they
        # only have chirp_data.
        try:
            chirp_data = dd.variables["polarised_chirp_PPVV_data"][:].data.transpose()
        except KeyError:
            chirp_data = dd.variables["chirp_data"][:].data.transpose()
    else:
        chirp_data = dd.variables["chirp_data"][:].data.transpose()

    # NB: BAS tutorial recommends converting to dB here: chirp = 10*np.log10(chirp)
    # QUESTION: However, the metadata says it's already in dBm?
    chirp_data = np.log10(chirp_data)

    # These are in PS71 (specified in 'projection' ncattrs)
    xx = dd.variables["x_coordinates"][:].data
    yy = dd.variables["y_coordinates"][:].data
    utc = dd.variables["UTC_time_layerData"][:].data
    # There was an error in the polargap data export.
    if dd.campaign == "POLARGAP":
        utc = None
    lon = dd.variables["longitude_layerData"][:].data
    lat = dd.variables["latitude_layerData"][:].data

    # In microseconds
    fast_time = dd.variables["fast_time"][:].data

    # Handle pulse <-> chirp interpolation, if necessary
    # pick_traces should be the variable that matches the {x, y}_coordinates and {srf, bed}_picks arrays
    # As discussed above, I thought about using presence of "traces_chirp" as flag instead of season
    # name, but then I'd have to figure which direction the interpolation went.
    # (FISS2016 has PriNumber_ variables, but doesn't require interpolation here.)
    if dd.campaign == "AGAP":
        # Chirp and Pulse traces do not align; PriNumber_{pulse, chirp} gives effective timestamps on the same "clock" for both.
        # All other data fields are provided for pulse trace numbers, and we need to find the equivalent chirp trace
        # for plotting on the chirp radargram.
        # traces_chirp = dd.variables["traces_chirp"][:].data
        traces_pulse = dd.variables["traces_pulse"][:].data
        pri_chirp = dd.variables["PriNumber_chirp"][:].data
        pri_pulse = dd.variables["PriNumber_pulse"][:].data

        # Figure out the equivalent pulse trace for every chirp trace,
        # then find positions for those
        chirp_traces_as_pulse = np.interp(pri_chirp, pri_pulse, traces_pulse)
        chirp_traces_as_pulse = list(map(int, chirp_traces_as_pulse))
        xx = xx[chirp_traces_as_pulse]
        yy = yy[chirp_traces_as_pulse]
        utc = utc[chirp_traces_as_pulse]
        lat = lat[chirp_traces_as_pulse]
        lon = lon[chirp_traces_as_pulse]

    print(
        f"Loaded BAS radargram. shape = {chirp_data.shape}, "
        f"len(xx) = {len(xx)}, len(fast_time) = {len(fast_time)} "
    )

    return (chirp_data, lat, lon, utc, fast_time)
