"""Write data/plants/gas_plant.yaml: an invented gas processing plant.

The plant is illustrative. It was written for this project to be large enough
that conflicts cannot be found by eye. It is not a drawing of any real plant.
Run:  python data/plants/make_gas_plant.py
"""
from pathlib import Path

import yaml

comps: list[dict] = []
conns: list[list[str]] = []
SERVICE = ["process_gas"]                  # the service of the section being written


def section(service):
    SERVICE[0] = service


def c(tag, kind, name, state, normal=None, service=None, **kw):
    d = {"tag": tag, "kind": kind, "name": name, "state": state}
    if normal and normal != state:
        d["normal"] = normal
    d.update(kw)
    d["service"] = service or SERVICE[0]
    comps.append(d)
    return tag


def link(*tags):
    for a, b in zip(tags, tags[1:]):
        conns.append([a, b])


# ---------------------------------------------------------------- inlet and separation
section("process_gas")
c("WH-MAN", "header", "Wellhead production manifold", "in_service", pressure_source=True)
c("L-100", "line", "Inlet flowline", "in_service")
c("SDV-100", "valve", "Inlet shutdown valve", "open")
c("V-100", "vessel", "Slug catcher", "in_service", pressure_source=True)
c("L-101", "line", "Slug catcher gas outlet", "in_service")
c("V-110", "vessel", "HP separator", "in_service", pressure_source=True)
link("WH-MAN", "L-100", "SDV-100", "V-100", "L-101", "V-110")
c("L-110G", "line", "HP separator gas outlet", "in_service")
c("SDV-110", "valve", "Compressor suction shutdown valve", "closed", normal="open")
c("L-SUCT", "line", "Compressor suction header", "in_service")
link("V-110", "L-110G", "SDV-110", "L-SUCT")
c("L-110L", "line", "HP separator liquid outlet", "in_service", service="condensate")
c("LV-110", "control_valve", "HP separator level valve", "open", service="condensate")
c("V-120", "vessel", "LP separator", "in_service", pressure_source=True)
link("V-110", "L-110L", "LV-110", "V-120")
c("L-120G", "line", "LP separator gas outlet", "in_service")
c("PCV-120", "control_valve", "Fuel gas pressure control valve", "open")
c("L-FG", "line", "Fuel gas header", "in_service", service="fuel_gas")
link("V-120", "L-120G", "PCV-120", "L-FG")

# ---------------------------------------------------------------- flare and closed drain
section("flare")
c("L-FLR", "line", "HP flare header", "in_service")
c("V-FLR", "vessel", "Flare knock-out drum", "in_service")
c("L-FLS", "line", "Flare stack line", "in_service")
link("L-FLR", "V-FLR", "L-FLS")
c("L-DRN", "line", "Closed drain header", "in_service", service="drain")
c("V-DRN", "vessel", "Closed drain drum", "in_service", service="drain")
link("L-DRN", "V-DRN")

# ---------------------------------------------------------------- compression: trains A, B, C
section("process_gas")
TRAINS = {
    # train: (number, suction valve, suction bypass, seal gas, recycle, discharge valve, compressor, relief)
    "A": dict(n=21, status="standby"),
    "B": dict(n=22, status="standby"),
    "C": dict(n=23, status="maintenance"),
}
for train, t in TRAINS.items():
    n = t["n"]
    maint = t["status"] == "maintenance"
    k = f"K-{n}0"
    c(f"XV-{n}1", "valve", f"Train {train} suction isolation valve", "closed", normal="open")
    c(f"BV-{n}1", "valve", f"Train {train} suction pressurisation bypass (small bore)",
      "open" if maint else "closed", normal="closed")
    c(f"L-{n}1", "line", f"Train {train} suction line", "in_service")
    link("L-SUCT", f"XV-{n}1", f"L-{n}1")
    link("L-SUCT", f"BV-{n}1", f"L-{n}1")
    c(f"V-{n}0", "vessel", f"Train {train} suction scrubber", "in_service")
    c(f"DR-{n}0", "valve", f"Train {train} scrubber drain valve", "closed")
    link(f"L-{n}1", f"V-{n}0")
    link(f"V-{n}0", f"DR-{n}0", "L-DRN")
    c(f"L-{n}0S", "line", f"Train {train} compressor suction", "in_service")
    c(k, "compressor", f"Train {train} gas compressor", "shutdown", normal="in_service", pressure_source=True)
    c(f"L-{n}0D", "line", f"Train {train} compressor discharge", "in_service")
    link(f"V-{n}0", f"L-{n}0S", k, f"L-{n}0D")
    c(f"XV-{n}5", "valve", f"Train {train} seal gas supply valve", "closed" if maint else "open",
      service="fuel_gas")
    link("L-FG", f"XV-{n}5", k)
    c(f"FV-{n}2", "control_valve", f"Train {train} anti-surge recycle valve", "closed", normal="open")
    link(f"L-{n}0D", f"FV-{n}2", f"L-{n}1")
    c(f"RV-{n}0", "valve", f"Train {train} relief valve inlet block valve", "open")
    c(f"L-{n}0R", "line", f"Train {train} relief line", "in_service")
    link(f"L-{n}0D", f"RV-{n}0", f"L-{n}0R")
    if maint:
        c(f"BF-{n}0", "blind", f"Blind flange fitted in place of PSV-{n}0", "installed",
          normal="not_installed", integrity="temporary")
        c(f"PSV-{n}0", "psv", f"Train {train} discharge relief valve", "removed", normal="closed")
        link(f"L-{n}0R", f"BF-{n}0", f"PSV-{n}0", "L-FLR")
    else:
        c(f"PSV-{n}0", "psv", f"Train {train} discharge relief valve", "closed")
        link(f"L-{n}0R", f"PSV-{n}0", "L-FLR")
    c(f"VNT-{n}0", "valve", f"Train {train} discharge vent to flare", "closed")
    link(f"L-{n}0D", f"VNT-{n}0", "L-FLR")
    c(f"E-{n}0", "exchanger", f"Train {train} aftercooler", "in_service")
    c(f"NRV-{n}0", "check_valve", f"Train {train} discharge non-return valve", "open")
    c(f"XV-{n}3", "valve", f"Train {train} discharge isolation valve", "closed", normal="open")
    c(f"L-{n}3", "line", f"Train {train} outlet to discharge header", "in_service")
    link(f"L-{n}0D", f"E-{n}0", f"NRV-{n}0", f"XV-{n}3", f"L-{n}3")

c("XV-TIE", "valve", "Train B / train C discharge cross-tie valve", "closed")
link("L-220D", "XV-TIE", "L-230D")
c("L-DISCH", "line", "Compressor discharge header", "in_service")
for n in (21, 22, 23):
    link(f"L-{n}3", "L-DISCH")

# ---------------------------------------------------------------- dehydration
c("XV-300", "valve", "Glycol contactor inlet valve", "open")
c("C-300", "vessel", "Glycol contactor", "in_service")
c("L-300", "line", "Contactor gas outlet", "in_service")
link("L-DISCH", "XV-300", "C-300", "L-300")
c("XV-301", "valve", "Dry gas filter inlet valve", "closed", normal="open")
c("F-300", "filter", "Dry gas filter", "shutdown", normal="in_service")
c("XV-302", "valve", "Dry gas filter outlet valve", "closed", normal="open")
c("L-301", "line", "Dry gas line", "in_service")
link("L-300", "XV-301", "F-300", "XV-302", "L-301")
c("BV-300", "valve", "Dry gas filter bypass valve", "open", normal="closed")
link("L-300", "BV-300", "L-301")
c("DR-300", "valve", "Dry gas filter drain valve", "closed")
link("F-300", "DR-300", "L-DRN")
c("C-310", "vessel", "Glycol regenerator", "in_service", service="glycol")
c("L-310", "line", "Rich glycol line", "in_service", service="glycol")
c("LV-310", "control_valve", "Contactor glycol level valve", "open", service="glycol")
link("C-300", "L-310", "LV-310", "C-310")
c("P-310", "pump", "Lean glycol pump", "in_service", pressure_source=True, service="glycol")
c("L-311", "line", "Lean glycol line", "in_service", service="glycol")
link("C-310", "P-310", "L-311", "C-300")

# ---------------------------------------------------------------- export gas and pig launcher
c("E-300", "exchanger", "Gas/gas exchanger", "in_service")
c("L-EXG", "line", "Export gas line", "in_service")
c("L-MTR", "line", "Export gas metering run", "in_service")
c("XV-500", "valve", "Export pipeline isolation valve", "open")
c("L-EXP", "header", "Export gas pipeline", "in_service", pressure_source=True)
link("L-301", "E-300", "L-EXG", "L-MTR", "XV-500", "L-EXP")
c("PL-500", "vessel", "Export pig launcher", "shutdown", normal="in_service")
c("XV-501", "valve", "Pig launcher main valve", "closed", normal="open")
c("XV-502", "valve", "Pig launcher kicker valve", "closed")
c("VNT-500", "valve", "Pig launcher vent valve", "open", normal="closed")
link("L-EXG", "XV-501", "PL-500")
link("L-MTR", "XV-502", "PL-500")
link("PL-500", "VNT-500", "L-FLR")

# ---------------------------------------------------------------- condensate stabilisation and export
section("condensate")
c("L-120L", "line", "LP separator liquid outlet", "in_service")
c("XV-400", "valve", "Stabiliser feed valve", "open")
c("C-400", "vessel", "Condensate stabiliser", "in_service", pressure_source=True)
c("L-400", "line", "Stabiliser bottoms", "in_service")
c("L-CS", "line", "Condensate pump suction header", "in_service")
link("V-120", "L-120L", "XV-400", "C-400", "L-400", "L-CS")
c("L-CD", "line", "Condensate pump discharge header", "in_service")
for p, state in (("A", "shutdown"), ("B", "shutdown"), ("C", "in_service")):
    maint = p == "B"
    c(f"SV-41{p}", "valve", f"Condensate pump {p} suction valve", "closed" if p != "C" else "open", normal="open")
    c(f"L-41{p}S", "line", f"Condensate pump {p} suction line", "in_service")
    c(f"P-41{p}", "pump", f"Condensate pump {p}", state, normal="in_service", pressure_source=True)
    c(f"L-41{p}D", "line", f"Condensate pump {p} discharge line", "in_service")
    c(f"NRV-41{p}", "check_valve", f"Condensate pump {p} non-return valve", "open")
    c(f"DV-41{p}", "valve", f"Condensate pump {p} discharge valve", "closed" if p != "C" else "open", normal="open")
    link("L-CS", f"SV-41{p}", f"L-41{p}S", f"P-41{p}", f"L-41{p}D", f"NRV-41{p}", f"DV-41{p}", "L-CD")
    c(f"DR-41{p}", "valve", f"Condensate pump {p} casing drain", "closed")
    link(f"L-41{p}S", f"DR-41{p}", "L-DRN")
    c(f"RV-41{p}", "valve", f"Condensate pump {p} relief block valve", "open")
    c(f"PSV-41{p}", "psv", f"Condensate pump {p} relief valve", "closed")
    link(f"L-41{p}D", f"RV-41{p}", f"PSV-41{p}", "L-FLR")
    c(f"MV-41{p}", "valve", f"Condensate pump {p} minimum-flow valve", "closed" if p != "C" else "open")
    link(f"L-41{p}D", f"MV-41{p}", "C-400")
c("XV-420", "valve", "Condensate export valve", "open")
c("L-CEX", "line", "Condensate export line", "in_service")
c("FQ-420", "line", "Condensate metering skid", "in_service")
c("XV-421", "valve", "Main oil line tie-in valve", "open")
c("MOL", "header", "Main oil line", "in_service", pressure_source=True, service="oil")
link("L-CD", "XV-420", "L-CEX", "FQ-420", "XV-421", "MOL")

# ---------------------------------------------------------------- utilities
# Utilities are separate services. Nitrogen has two deliberate purge tie-ins into
# process gas. Instrument air and fire water have no connection to process piping.
section("nitrogen")
c("N2-HDR", "header", "Nitrogen header", "in_service", pressure_source=True)
c("XV-610", "valve", "Train C nitrogen purge valve", "closed")
c("L-N2-610", "line", "Train C nitrogen purge spool", "in_service")
c("XV-611", "valve", "Train C nitrogen purge inlet valve", "closed")
link("N2-HDR", "XV-610", "L-N2-610", "XV-611", "V-230")
c("XV-620", "valve", "Pig launcher nitrogen purge valve", "closed")
link("N2-HDR", "XV-620", "PL-500")
section("instrument_air")
c("IA-HDR", "header", "Instrument air header", "in_service", pressure_source=True)
c("L-IA", "line", "Instrument air distribution to valve actuators", "in_service")
link("IA-HDR", "L-IA")
section("fire_water")
c("FW-HDR", "header", "Fire water ring main", "in_service", pressure_source=True)
c("XV-640", "valve", "Fire water to stabiliser deluge", "closed")
c("L-640", "line", "Stabiliser deluge line", "in_service")
link("FW-HDR", "XV-640", "L-640")

plant = {
    "unit": "Gas processing plant (illustrative)",
    "description": ("Invented for Blind Flange. Inlet separation, three compression trains, glycol "
                    "dehydration, export gas with a pig launcher, condensate stabilisation and export, "
                    "flare, closed drain and utilities. Not a drawing of any real plant."),
    "components": comps,
    # Services a connection may cross on purpose, as [from, to]: pressure from the first
    # may legitimately enter the second. Decides which sources are worth listing; every
    # connection still carries pressure either way.
    "tie_ins": [
        ["process_gas", "condensate"],   # separator liquid outlets
        ["process_gas", "fuel_gas"],     # LP separator gas let down to fuel gas
        ["fuel_gas", "process_gas"],     # compressor seal gas
        ["process_gas", "glycol"],       # glycol contactor
        ["process_gas", "flare"], ["condensate", "flare"],
        ["process_gas", "drain"], ["condensate", "drain"],
        ["condensate", "oil"],           # condensate export into the main oil line
        ["nitrogen", "process_gas"],     # purge connections
    ],
    "connections": conns,
}
header = ("# GENERATED by data/plants/make_gas_plant.py. Edit that script, not this file.\n"
          "# An invented gas processing plant. Illustrative only: not a drawing of any real plant.\n")
out = Path(__file__).with_name("gas_plant.yaml")
out.write_text(header + yaml.safe_dump(plant, sort_keys=False, width=120), encoding="utf-8", newline="\n")
print(f"Wrote {out}: {len(comps)} components, {len(conns)} connections")
