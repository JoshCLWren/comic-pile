# GitHub API Deprecation Notice

## Projects (classic) GraphQL API Deprecation

**Status:** ⚠️ Deprecated (GitHub notice issued)

GitHub has deprecated the Projects (classic) GraphQL API in favor of the new Projects experience. 

### What This Means

- **Projects (classic)**: The existing GraphQL API for project boards and cards
- **New Projects experience**: The replacement API with enhanced features

### References

- GitHub Changelog: [GraphQL: Projects (classic) sunset notice](https://github.blog/changelog/2024-05-23-sunset-notice-projects-classic/)
- Migration Guide: Available in GitHub's developer documentation

### Current Code Status

✅ **Comic Pile does NOT currently use the deprecated Projects (classic) API**

The codebase has been audited and found to have no dependencies on:
- GraphQL project card operations
- Project board management via GraphQL
- Any Projects (classic) API endpoints

### Preventive Measures

To prevent future accidental usage of the deprecated API:

1. **Code Review**: Any new GitHub API usage should be reviewed for deprecation status
2. **Documentation**: Always check GitHub's API documentation for the latest supported endpoints
3. **Testing**: Include API integration tests that verify current API compatibility
4. **Monitoring**: Stay updated on GitHub API changes through official channels

### If You Need Project Management

For project board functionality in Comic Pile:

- Use GitHub's web interface for project management
- Consider GitHub Issues + Labels + Projects (new) workflow
- Evaluate third-party project management tools if needed
- Implement custom solutions using supported GitHub APIs

### Best Practices

- Always use the latest stable GitHub API versions
- Monitor GitHub's developer blog for deprecation notices
- Plan for API migrations when deprecations are announced
- Keep dependencies up to date to benefit from latest API features

---

*This documentation was added as part of issue #363 fix to prevent future usage of deprecated GitHub APIs.*