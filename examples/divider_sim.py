"""SPICE simulation of the voltage divider from a single SKiDL source of truth.

Same circuit as divider.py; converted for SPICE via convert_for_spice().

Requires: ngspice on PATH (pacman -S ngspice), inspice + matplotlib in .venv.

Run:  source ../env.sh && ../.venv/bin/python divider_sim.py
"""

import matplotlib.pyplot as plt
from InSpice import Simulator
from InSpice.Unit import *
from skidl import KICAD10, TEMPLATE, Net, Part, set_default_tool
from skidl.pyspice import C, R, SPICE, generate_netlist, reset

reset()
# reset() can drop the tool config; KiCad libs are the source of truth for parts.
set_default_tool(KICAD10)

# --- The circuit (identical topology to divider.py) ---
vin, vout, gnd = Net("VI"), Net("VO"), Net("GND")

r1, r2 = 2 * Part(
    "Device",
    "R",
    dest=TEMPLATE,
    footprint="Resistor_SMD.pretty:R_0805_2012Metric",
)
r1.value, r2.value = "10K", "4.7K"
r1.tag, r2.tag = "R1", "R2"

c1 = Part(
    "Device",
    "C",
    dest=TEMPLATE,
    footprint="Capacitor_SMD.pretty:C_0805_2012Metric",
)
c1.value = "100N"
c1.tag = "C1"

vin.connect(r1[1])
vout.connect(r1[2], r2[1], c1[1])
gnd.connect(r2[2], c1[2])

# --- Convert KiCad parts to their SPICE equivalents ---
set_default_tool(SPICE)
r1.convert_for_spice(R, {1: "p", 2: "n"})
r2.convert_for_spice(R, {1: "p", 2: "n"})
c1.convert_for_spice(C, {1: "p", 2: "n"})

# --- Run the simulation: source is a 0->5V pulse; op point is its t=0 value ---
circuit = generate_netlist()
# VoltageSource positional slots: DC, AC, then the tran expression. Set
# dc_value=None so the raw PULSE() string lands in the tran slot.
pulse_src = circuit.V("source", vin.name, gnd.name, 0 @ u_V)
pulse_src.dc_value = None
pulse_src.tran_value = "PULSE(0 5 0 1n 1n 5m 10m)"

simulator = Simulator.factory()
sim = simulator.simulation(circuit, temperature=25, nominal_temperature=25)

print("DC operating point:")
analysis = sim.operating_point()
for nd in analysis.nodes.values():
    print(f"  {str(nd)}: {float(nd[0]):.3f} V")

# --- Transient: RC charging through the divider ---
waveforms = sim.transient(step_time=0.01 @ u_ms, end_time=10 @ u_ms)

time = waveforms.time
fig = plt.figure()
plt.title("Divider + cap: pulse input vs output")
plt.xlabel("Time (ms)")
plt.ylabel("Voltage (V)")
plt.plot(time * 1000, waveforms["vi"])
plt.plot(time * 1000, waveforms["vo"])
plt.legend(("VI (in)", "VO (out)"))
fig.savefig("divider_sim.png", bbox_inches="tight")
print("Wrote divider_sim.png")
