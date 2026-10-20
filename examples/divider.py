"""Voltage divider demo: 5V in, 3.3-ish V out of a resistive divider.

Run:  source ../env.sh && ../.venv/bin/python divider.py
"""

from skidl import *

# Input & output voltages and ground reference.
vin, vout, gnd = Net("VI"), Net("VO"), Net("GND")

r1, r2 = 2 * Part(
    "Device",
    "R",
    dest=TEMPLATE,
    footprint="Resistor_SMD.pretty:R_0805_2012Metric",
)
r1.value, r2.value = "10K", "4.7K"
r1.tag, r2.tag = "R1", "R2"

vin.connect(r1[1])
vout.connect(r1[2], r2[1])
gnd.connect(r2[2])

ERC()
generate_netlist(tool=KICAD10)
generate_svg(tool=KICAD10, top_name="divider")
