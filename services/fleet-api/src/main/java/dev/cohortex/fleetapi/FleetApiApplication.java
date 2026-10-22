package dev.cohortex.fleetapi;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.info.License;
import java.time.Clock;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

/** Cohortex fleet-api: read-only REST API over the serving store (C3, WP-04). */
@SpringBootApplication
public class FleetApiApplication {

  public static void main(String[] args) {
    SpringApplication.run(FleetApiApplication.class, args);
  }

  @Bean
  Clock clock() {
    return Clock.systemUTC();
  }

  @Bean
  OpenAPI fleetApiOpenApi() {
    return new OpenAPI()
        .info(
            new Info()
                .title("Cohortex fleet-api")
                .version("v1")
                .description(
                    "Read-only reliability API over Backblaze HDD and Alibaba SSD telemetry."
                        + " AFR intervals are exact Poisson 95%. Errors are RFC 9457 problem"
                        + " details.")
                .license(new License().name("MIT")));
  }
}
