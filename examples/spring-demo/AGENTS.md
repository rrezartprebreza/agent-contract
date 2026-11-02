# Team instructions

Use @WebMvcTest for controller tests.
Prefer field injection for services.

## Historical example (not active guidance)

```text
Use @Value for configuration.
```

<!-- agentcontract:begin -->
## Approved engineering policies

Generated from the approved AgentContract policy.
- Do not use field injection. Inject dependencies through the constructor. [spring.no-field-injection; error]
- Do not use @Value. Use validated configuration properties. [spring.no-value; warning]
- Do not use @WebMvcTest. Use the repository-approved integration testing approach. [spring.no-webmvctest; error]
<!-- agentcontract:end -->
