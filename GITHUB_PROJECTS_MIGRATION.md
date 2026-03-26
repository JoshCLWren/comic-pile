# GitHub Projects Migration Guide

## Background
GitHub Projects (classic) is being deprecated in favor of the new Projects experience. See: https://github.blog/changelog/2024-05-23-sunset-notice-projects-classic/

## Migration Path
Since the Comic Pile project doesn't currently use GitHub Projects, here's how to implement project management features using the new Projects experience:

### 1. Use the New Projects REST API
```python
# Example using requests (async support available)
import requests

headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Create a new project
project_data = {
    "name": "Comic Pile Tasks",
    "body": "Project for tracking comic pile development tasks",
}
response = requests.post(
    "https://api.github.com/repos/JoshCLWren/comic-pile/projects",
    json=project_data,
    headers=headers
)
```

### 2. Key Differences from Classic Projects
- **REST API instead of GraphQL** - Use standard HTTP requests
- **No Project Cards** - Use issues and issue collections instead
- **Better automation** - Native GitHub Actions integration
- **Improved UI** - New table and board views

### 3. Integration Points
- **Issue Management** - Already implemented via `gh` CLI in scripts
- **Project Creation** - Add project creation to setup scripts
- **Automation** - Use GitHub Actions for project updates

### 4. Migration Timeline
- **Now**: Document the migration path
- **Q3 2024**: Implement basic project features
- **Q4 2024**: Full project management integration

## Next Steps
1. Choose between REST API or GraphQL (REST is recommended for new projects)
2. Design project structure based on comic pile workflows
3. Implement project creation and issue linking
4. Add project views to the frontend

## Resources
- [New Projects Experience Documentation](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/creating-a-project)
- [Projects REST API](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects)
- [Migration Guide](https://docs.github.com/en/issues/planning-and-tracking-with-projects/troubleshooting-projects/migrating-projects-from-classic-to-the-new-experience)