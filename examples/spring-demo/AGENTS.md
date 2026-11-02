# Team instructions

Use @WebMvcTest for controller tests.
Prefer field injection for services.

## Historical example (not active guidance)

```text
Use @Value for configuration.
```

## Configuration

Read settings like this:

```java
class PaymentClient {
    @Value("${payments.url}") String url;
}
```

❌ Counter-example (kept for teaching, not flagged):

```java
class LegacyService {
    @Autowired Repository repository;
}
```

<!-- agentaccord:begin -->
## Approved engineering policies

Generated from the approved AgentAccord policy.
- Do not use @Data. Use records or explicit accessors. [custom.no-lombok-data; warning]
- Do not use field injection. Inject dependencies through the constructor. [spring.no-field-injection; error]
- Do not use @Value. Use validated configuration properties. [spring.no-value; warning]
- Do not use @WebMvcTest. Use the repository-approved integration testing approach. [spring.no-webmvctest; error]
<!-- agentaccord:end -->
