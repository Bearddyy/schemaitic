"""Capacitor sweep: 4 caps in parallel with the bottom resistor of the divider.

One transient simulation per capacitor value; VO traces stacked on one plot to
show how the parallel cap sets the charging time constant
tau = C * (R1 || R2) at the output node.

Requires: ngspice, inspice, matplotlib.
Run:  source ../env.sh && ../.venv/bin/python cap_sweep.py
"""

import numpy as np
import matplotlib.pyplot as plt
from InSpice import Simulator
from InSpice.Unit import *
from skidl import KICAD10, TEMPLATE, Net, Part, set_default_tool
from skidl.pyspice import C, R, SPICE, generate_netlist, reset

CAP_VALUES = ["1N", "10N", "100N", "1U"]
R1, R2 = 10e3, 4.7e3


def simulate_cap(cap_value: str) -> tuple[np.ndarray, np.ndarray]:
    """Build divider + parallel cap, run transient, return (time_s, vo_V)."""
    reset()
    set_default_tool(KICAD10)

    vin, vout, gnd = Net("VI"), Net("VO"), Net("GND")
    r1, r2 = 2 * Part(
        "Device", "R", dest=TEMPLATE,
        footprint="Resistor_SMD.pretty:R_0805_2012Metric",
    )
    r1.value, r2.value, r1.tag, r2.tag = "10K", "4.7K", "R1", "R2"
    c1 = Part(
        "Device", "C", dest=TEMPLATE,
        footprint="Capacitor_SMD.pretty:C_0805_2012Metric",
    )
    c1.value, c1.tag = cap_value, "C1"

    vin.connect(r1[1])
    vout.connect(r1[2], r2[1], c1[1])
    gnd.connect(r2[2], c1[2])

    set_default_tool(SPICE)
    r1.convert_for_spice(R, {1: "p", 2: "n"})
    r2.convert_for_spice(R, {1: "p", 2: "n"})
    c1.convert_for_spice(C, {1: "p", 2: "n"})

    circuit = generate_netlist()
    src = circuit.V("source", vin.name, gnd.name, 0 @ u_V)
    src.dc_value = None
    src.tran_value = "PULSE(0 5 0 1n 1n 5m 10m)"

    sim = Simulator.factory().simulation(circuit, temperature=25,
                                         nominal_temperature=25)
    waveforms = sim.transient(step_time=0.005 @ u_ms, end_time=10 @ u_ms)
    t = np.asarray(waveforms.time, dtype=float)
    vo = np.asarray(waveforms["vo"], dtype=float)
    return t, vo


fig = plt.figure()
plt.title("Divider with cap across bottom resistor: C sweep")
plt.xlabel("Time (ms)")
plt.ylabel("VO (V)")

for cap in CAP_VALUES:
    t, vo = simulate_cap(cap)
    tau_ms = (R1 * R2 / (R1 + R2)) * float(cap[:-1]) * {"N": 1e-9, "U": 1e-6}[cap[-1]] * 1e3
    plt.plot(t * 1000, vo, label=f"C = {cap} (τ = {tau_ms:.3f} ms)")
    plateau = float(vo[int(np.argmax(t > 4e-3))])
    print(f"C={cap:>4}: tau_theory={tau_ms:.4f} ms, VO at 4ms = {plateau:.4f} V")

plt.legend()
plt.ylim(0, 2)
fig.savefig("cap_sweep.png", bbox_inches="tight")
print("Wrote cap_sweep.png")
