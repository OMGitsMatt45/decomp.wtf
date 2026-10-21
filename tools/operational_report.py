"""Make all failures visible even when GitHub caps individual error annotations."""

from pathlib import Path
import xml.etree.ElementTree as ET


def main():
    path = Path("operational-results.xml")
    if not path.exists():
        return
    cases = list(ET.parse(path).iter("testcase"))
    failed = [case for case in cases if case.find("failure") is not None or case.find("error") is not None]
    skipped = [case for case in cases if case.find("skipped") is not None]
    summary = f"{len(cases) - len(failed) - len(skipped)} passed, {len(failed)} failed/errors, {len(skipped)} skipped\n"
    summary += "\n".join(case.get("classname", "") + "::" + case.get("name", "") for case in failed)
    escape = lambda value: value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print("::notice::" + escape(summary))
    modules = {}
    for case in failed:
        module = case.get("classname", "")
        if module not in modules:
            node = case.find("failure")
            if node is None:
                node = case.find("error")
            modules[module] = (node.text or node.get("message", ""))[-4000:]
    if modules:
        print("::error::" + escape("\n\n".join(name + ":\n" + message for name, message in modules.items())[-60000:]))


if __name__ == "__main__":
    main()
