package dev.cohortex.fleetapi.it;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.env.Environment;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Shared HTTP plumbing for the integration tests: plain JDK client against the running app. */
abstract class ApiTestBase {

  static final JsonMapper JSON = JsonMapper.builder().build();
  private static final HttpClient HTTP =
      HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();

  @Autowired Environment environment;

  @DynamicPropertySource
  static void database(DynamicPropertyRegistry registry) {
    TestDatabase.register(registry);
  }

  /** A response with its status, content type and parsed JSON body. */
  record Reply(int status, String contentType, JsonNode body) {}

  Reply get(String pathAndQuery) throws IOException, InterruptedException {
    String port = environment.getRequiredProperty("local.server.port");
    HttpRequest request =
        HttpRequest.newBuilder(URI.create("http://localhost:" + port + pathAndQuery))
            .timeout(Duration.ofSeconds(30))
            .header("Accept", "application/json, application/problem+json")
            .GET()
            .build();
    HttpResponse<String> response = HTTP.send(request, HttpResponse.BodyHandlers.ofString());
    String contentType = response.headers().firstValue("Content-Type").orElse("");
    JsonNode body = response.body().isEmpty() ? null : JSON.readTree(response.body());
    return new Reply(response.statusCode(), contentType, body);
  }
}
