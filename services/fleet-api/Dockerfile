# fleet-api image. Build from the repo root (the Gradle build and db/migrations live there):
#   docker build -f services/fleet-api/Dockerfile -t cohortex/fleet-api .

# ---- build: Gradle wrapper on JDK 25 (matches the toolchain, so nothing is downloaded by foojay)
FROM eclipse-temurin:25-jdk AS build
WORKDIR /src
COPY gradlew settings.gradle.kts build.gradle.kts gradle.properties ./
COPY gradle gradle
COPY services/fleet-api/build.gradle.kts services/fleet-api/
# Warm the dependency cache in its own layer.
RUN ./gradlew --no-daemon --no-configuration-cache -q :services:fleet-api:dependencies > /dev/null
COPY services/fleet-api/src services/fleet-api/src
RUN ./gradlew --no-daemon --no-configuration-cache :services:fleet-api:bootJar

# ---- runtime: JRE only, non-root
FROM eclipse-temurin:25-jre
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 fleet \
 && useradd --system --uid 10001 --gid fleet --no-create-home fleet
WORKDIR /app
COPY --from=build /src/services/fleet-api/build/libs/fleet-api.jar /app/fleet-api.jar
# Flyway applies the repo's migrations on startup (V1 = contracts §2 DDL).
COPY db/migrations /app/db/migrations
ENV FLYWAY_LOCATIONS=filesystem:/app/db/migrations \
    JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75"
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=40s --retries=5 \
  CMD curl -fsS http://localhost:8080/actuator/health/readiness || exit 1
ENTRYPOINT ["java", "-jar", "/app/fleet-api.jar"]
