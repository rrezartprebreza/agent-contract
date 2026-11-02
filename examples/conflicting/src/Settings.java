import org.springframework.beans.factory.annotation.Value;
class Settings {
    @Value("${app.name}")
    private String name;
}
