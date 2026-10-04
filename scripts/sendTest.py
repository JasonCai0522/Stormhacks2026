import json
import os
import sys

def send(held):
    with open("inputs.tmp", "w") as f:
        json.dump({"held": held}, f)
    os.replace("inputs.tmp", "inputs.json")

# Everything typed after the script name becomes the held list.
# No arguments = release everything.
send(sys.argv[1:])
print("Sent:", sys.argv[1:])