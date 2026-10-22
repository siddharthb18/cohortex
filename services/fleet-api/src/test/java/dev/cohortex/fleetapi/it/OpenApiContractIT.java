package dev.cohortex.fleetapi.it;

import static org.assertj.core.api.Assertions.assertThat;

import dev.cohortex.fleetapi.RepoPaths;
import java.nio.file.Files;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import org.junit.jupiter.api.Test;
import org.yaml.snakeyaml.Yaml;
import tools.jackson.databind.JsonNode;

/**
 * FR-API-7: the OpenAPI document served by the running app ({@code /v3/api-docs}) contains every
 * path and method of the hand-written contract {@code contracts/openapi/fleet-api.yaml}, and the
 * contract documents every {@code /v1} operation the app serves.
 */
@IntegrationTest
class OpenApiContractIT extends ApiTestBase {

  @Test
  void servedSpecMatchesContractPaths() throws Exception {
    Map<String, Object> contract =
        new Yaml()
            .load(Files.readString(RepoPaths.resolve("contracts/openapi/fleet-api.yaml")));
    assertThat(String.valueOf(contract.get("openapi"))).startsWith("3.1");

    Reply served = get("/v3/api-docs");
    assertThat(served.status()).isEqualTo(200);
    JsonNode spec = served.body();
    assertThat(spec.get("openapi").asString()).startsWith("3.1");

    Set<String> contractOps = new TreeSet<>();
    @SuppressWarnings("unchecked")
    Map<String, Map<String, Object>> paths = (Map<String, Map<String, Object>>) contract.get("paths");
    paths.forEach(
        (path, item) ->
            item.keySet().stream()
                .filter(OpenApiContractIT::isMethod)
                .forEach(m -> contractOps.add(m + " " + path)));

    Set<String> servedOps = new TreeSet<>();
    JsonNode servedPaths = spec.get("paths");
    for (Map.Entry<String, JsonNode> path : servedPaths.properties()) {
      for (Map.Entry<String, JsonNode> op : path.getValue().properties()) {
        if (isMethod(op.getKey())) {
          servedOps.add(op.getKey() + " " + path.getKey());
        }
      }
    }

    assertThat(contractOps).isNotEmpty();
    assertThat(servedOps).containsAll(contractOps);
    Set<String> servedV1 = new TreeSet<>();
    servedOps.stream().filter(op -> op.contains(" /v1/")).forEach(servedV1::add);
    assertThat(contractOps).containsAll(servedV1);
  }

  private static boolean isMethod(String key) {
    return Set.of("get", "put", "post", "delete", "patch", "head", "options").contains(key);
  }
}
