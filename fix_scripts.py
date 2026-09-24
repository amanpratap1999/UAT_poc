import glob, re
for f in glob.glob('scripts/**/*.py', recursive=True):
    content = open(f, 'r', encoding='utf8').read()
    content = content.replace('sys.path.insert(0, str(src_dir))\n\nfrom agent.core.config import get_settings', 'from agent.core.config import get_settings\nsys.path.insert(0, str(src_dir))')
    content = content.replace('if not key: return "None"', 'if not key:\n        return "None"')
    content = content.replace('if len(key) <= 8: return "****"', 'if len(key) <= 8:\n        return "****"')
    open(f, 'w', encoding='utf8').write(content)
