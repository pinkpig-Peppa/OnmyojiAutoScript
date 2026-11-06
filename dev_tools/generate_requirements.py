# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import argparse
import os
import subprocess

from module.logger import logger

PYTHON_QML_REQUIREMENT = "pyside6==6.4.3\n"
TMP_REQUIREMENTS_IN = "requirements-in.tmp.txt"

def generate(qml: bool=False):
    with open("requirements-in.txt", "r", encoding="utf-8") as f:
        content = f.read()

    # 只在内存和临时输入文件里增删 pyside6，不要回写 requirements-in.txt：
    # 原来非 --qml 分支会把它从源文件里删掉，--qml 分支则根本没插入。
    if qml:
        if PYTHON_QML_REQUIREMENT.strip() not in content:
            content = content.rstrip("\n") + "\n" + PYTHON_QML_REQUIREMENT
    else:
        content = content.replace(PYTHON_QML_REQUIREMENT, "")

    with open(TMP_REQUIREMENTS_IN, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        # 执行命令 pip-compile --annotation-style=line --output-file=requirements.txt <tmp>
        result = subprocess.run(["pip-compile", "--annotation-style=line",
                                 "--output-file=requirements.txt", TMP_REQUIREMENTS_IN])
        if result.returncode != 0:
            logger.error(f"pip-compile failed with return code {result.returncode}, requirements.txt not updated")
            return
    finally:
        if os.path.exists(TMP_REQUIREMENTS_IN):
            os.remove(TMP_REQUIREMENTS_IN)

    with open("requirements.txt", "r", encoding="utf-8") as f:
        content = f.read()
        content = content.replace('''--index-url https://pypi.tuna.tsinghua.edu.cn/simple
--trusted-host pypi.tuna.tsinghua.edu.cn''', '')
    with open("requirements.txt", "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("requirements.txt generated")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate requirements.txt")
    parser.add_argument(
        "--qml",
        action="store_true",
        help="Use qml",
    )
    args, _ = parser.parse_known_args()
    qml = True if args.qml else False
    logger.attr("QML", qml)

    generate(qml)


