"""Bounded discovery from filenames; never executes project scripts."""
import re
LANGUAGES = {'.json': 'JSON', '.yaml': 'YAML', '.yml': 'YAML', '.java': 'Java', '.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript', '.js': 'JavaScript', '.cs': 'C#', '.go': 'Go', '.rs': 'Rust'}
MANIFESTS = {'pom.xml': 'Maven', 'build.gradle': 'Gradle', 'build.gradle.kts': 'Gradle', 'package.json': 'Node.js', 'pyproject.toml': 'Python', 'Cargo.toml': 'Cargo', 'go.mod': 'Go'}


def discover(root):
    from .cli import EXCLUDED
    languages, manifests, instructions = {}, [], []
    count = 0
    def walk_error(error):
        raise error
    for directory, dirs, files in root.walk(on_error=walk_error, follow_symlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
        for name in sorted(files):
            count += 1
            if count > 10_000:
                raise ValueError('Discovery exceeds 10,000 file entries')
            path = directory / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            language = LANGUAGES.get(path.suffix)
            if language:
                languages[language] = languages.get(language, 0) + 1
            if name in MANIFESTS:
                manifests.append(dict(path=rel, technology=MANIFESTS[name]))
            if name in {'AGENTS.md', 'CLAUDE.md', 'SKILL.md', 'copilot-instructions.md'} or name.endswith('.instructions.md'):
                instructions.append(rel)
    return dict(languages=languages, manifests=manifests, instructions=instructions,
                java=dict(zip(('version', 'source'), java_version(root))) if 'Java' in languages else None,
                limitations=['Discovery uses file names and declared Java versions; it does not infer framework versions or conventions.'])


# Newest Java release whose syntax the bundled tree-sitter-java grammar parses completely.
# Java 25 module imports and statements before super(...) are not parsed yet.
PARSER_JAVA = 24

VERSION = r'(1\.\d+|\d+)'
JAVA_DECLARATIONS = {
    'pom.xml': [rf'<maven\.compiler\.release>\s*{VERSION}\s*<', rf'<release>\s*{VERSION}\s*</release>',
                rf'<java\.version>\s*{VERSION}\s*<', rf'<maven\.compiler\.source>\s*{VERSION}\s*<',
                rf'<source>\s*{VERSION}\s*</source>'],
    'build.gradle.kts': [r'JavaLanguageVersion\.of\(\s*(\d+)\s*\)', r'jvmToolchain\(\s*(\d+)\s*\)',
                         r'sourceCompatibility\s*=\s*JavaVersion\.VERSION_(\d+(?:_\d+)?)',
                         rf'sourceCompatibility\s*=\s*[\'"]?{VERSION}\b'],
    '.java-version': [rf'\A\s*{VERSION}'],
    '.sdkmanrc': [r'^java\s*=\s*(\d+)'],
    '.tool-versions': [r'^java\s+(?:[A-Za-z]+-)*(\d+)'],
}
JAVA_DECLARATIONS['build.gradle'] = JAVA_DECLARATIONS['build.gradle.kts']


def normalize_java(value):
    value = value.replace('_', '.')
    major = int(value.split('.')[1] if value.startswith('1.') else value.split('.')[0])
    return major if 5 <= major <= 99 else None


def java_version(root):
    """The Java release a project declares in its build or version files, without running the build."""
    candidates = [root / name for name in JAVA_DECLARATIONS]
    # Multi-module and monorepo layouts often keep the build one folder down.
    candidates += sorted(path for name in ('pom.xml', 'build.gradle.kts', 'build.gradle')
                         for path in root.glob('*/' + name))
    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for pattern in JAVA_DECLARATIONS[path.name]:
            match = re.search(pattern, text, re.MULTILINE)
            if match and (version := normalize_java(match.group(1))):
                return version, path.relative_to(root).as_posix()
    return None, None
