"""Generate the standalone Python liquid-transfer simulation for an approved design."""

from app.design_workflow import workflow_state
from app.protocol_preview import validate_protocol
from app.software_guidance import build_software_guidance


def build_program(project: dict) -> str:
    if not workflow_state(project)["machine_approved"]:
        raise ValueError("Approve the machine before generating its program.")
    template = build_software_guidance(project)["protocol_template"]
    transfers = validate_protocol(template)
    binding = template["binding"]
    stock = template["current_preparation"]["stock_concentration"]
    rows = []
    for index, transfer in enumerate(transfers, 1):
        destination = transfer.get("destination_well") or f"Tube {index}"
        row = (destination, transfer["target"], transfer["stock_volume_ul"],
               transfer["diluent_volume_ul"])
        rows.append(f"    {row!r},")

    preparations = "\n".join(rows)
    return f'''"""Simulate this preparation with Python 3. Run: python program.py

Volumes are in microlitres. This program operates on an in-memory deck.
"""

PLATFORM = {binding["platform"]!r}
REVISION = {binding["project_revision"]!r}
STOCK = {stock!r}

# Destination, target concentration, stock volume (uL), diluent volume (uL).
PREPARATIONS = [
{preparations}
]


def simulate():
    deck = {{}}
    consumed = {{"stock": 0.0, "diluent": 0.0}}
    tips = 0
    print(f"{{PLATFORM}} | revision {{REVISION}} | stock {{STOCK}}")
    for destination, target, stock_ul, diluent_ul in PREPARATIONS:
        deck[destination] = 0.0
        for source, volume in (("stock", stock_ul), ("diluent", diluent_ul)):
            if volume > 0:
                tips += 1
                consumed[source] += volume
                print(f"  Pick up tip {{tips}} and aspirate {{volume:g}} uL from {{source}}")
                deck[destination] += volume
                print(f"  Transfer {{volume:g}} uL from {{source}} to {{destination}}")
                print("  Discard tip")
        print(f"{{destination}}: {{deck[destination]:g}} uL total at planned {{target}}")
    print(f"Total stock {{consumed['stock']:g}} uL, "
          f"diluent {{consumed['diluent']:g}} uL, {{tips}} tips")
    return deck


if __name__ == "__main__":
    simulate()
'''
