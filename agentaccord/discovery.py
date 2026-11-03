"""Bounded discovery from filenames; never executes project scripts."""
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
                limitations=['Discovery uses file names; it does not infer framework versions or conventions.'])
