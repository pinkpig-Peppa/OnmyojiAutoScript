import json
import os
from pathlib import Path


class Addition:
    @classmethod
    def load_additions(cls) -> dict:
        result = {}
        files: str = ['en-US', 'zh-CN']
        for file in files:
            file_path = Path.cwd() / 'assets' / 'i18n' / f'{file}.json'
            result[file] = {}
            if not file_path.exists():
                continue
            with open(str(file_path), 'r', encoding='utf-8') as f:
                result[file] = json.load(f)
        return result


class I18n(Addition):
    file_zh_cn = Path.cwd() / 'module' / 'config' / 'i18n' / 'zh-CN.json'

    @classmethod
    def trans_zh_cn(cls, text) -> str:
        cn_zh_data = cls.load_zh_cn()
        return cn_zh_data[text] if text in cn_zh_data else text

    @classmethod
    def save_zh_cn(cls, data) -> None:
        # 只接受 str -> str 的映射，避免任意 JSON（含列表/嵌套对象）覆盖翻译文件
        if not isinstance(data, dict):
            raise ValueError('translation payload must be a dict')
        for key, value in data.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError('translation payload must be str -> str')
        I18n.file_zh_cn.parent.mkdir(parents=True, exist_ok=True)
        s = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False, default=str)
        # 原子写入，避免进程中断后留下截断的翻译文件
        tmp_path = I18n.file_zh_cn.with_name(I18n.file_zh_cn.name + '.tmp')
        with open(str(tmp_path), 'w', encoding='utf-8') as f:
            f.write(s)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(I18n.file_zh_cn))

    @classmethod
    def load_zh_cn(cls) -> dict:
        if not I18n.file_zh_cn.exists():
            return {}
        with open(str(I18n.file_zh_cn), 'r', encoding='utf-8') as f:
            return json.load(f)


if __name__ == '__main__':
    print(I18n.load_zh_cn())
