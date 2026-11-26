"""Print one history line: the score JSON plus the commit it was produced from."""
import json
import sys

d = json.load(open(sys.argv[1]))
d["commit"] = sys.argv[2]
d.pop("first_failure_by_command", None)
print(json.dumps(d, sort_keys=True))
