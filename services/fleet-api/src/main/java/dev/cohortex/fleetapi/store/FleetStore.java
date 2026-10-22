package dev.cohortex.fleetapi.store;

import dev.cohortex.fleetapi.api.Dtos.AlertItem;
import dev.cohortex.fleetapi.api.Dtos.FailedDrive;
import dev.cohortex.fleetapi.api.Dtos.ModelItem;
import dev.cohortex.fleetapi.web.Granularity;
import dev.cohortex.fleetapi.web.PageParams;
import dev.cohortex.fleetapi.web.Source;
import dev.cohortex.fleetapi.web.Window;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.RowCallbackHandler;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * Read-only SQL over the serving store (contracts §2). Every value reaches the database as a bind
 * parameter; the only text spliced into SQL comes from fixed constants in this class or from enum
 * constants ({@link Granularity#id()}), never from a request (ADR-001).
 */
@Repository
public class FleetStore {

  private final JdbcClient jdbc;

  public FleetStore(JdbcClient jdbc) {
    this.jdbc = jdbc;
  }

  /** Per-period totals of a cohort. */
  public record PeriodTotals(LocalDate periodStart, long driveDays, long failures) {}

  /** A model's totals in a window plus its drive count on its last day inside the window. */
  public record ModelWindowTotals(
      String model, long driveDays, long failures, long lastDayDriveCount) {}

  /** Fleet totals for {@code /v1/fleet/summary}. */
  public record FleetTotals(long drives, long driveDays, long failures) {}

  /** One period of a SMART attribute trend. */
  public record SmartTrendRow(
      LocalDate periodStart, Double p50, Double p95, double nonzeroShare, long nDrives) {}

  // ------------------------------------------------------------------ models

  /** {@code drive_count} is the model's count on its latest day in {@code cohort_daily}. */
  public List<ModelItem> models(String source, String media, PageParams page) {
    Filter f = modelFilter(source, media);
    return jdbc.sql(
            """
            SELECT m.id, m.source, m.model, m.media, m.capacity_bytes,
                   COALESCE(latest.drive_count, 0) AS drive_count
            FROM drive_model m
            LEFT JOIN LATERAL (
              SELECT c.drive_count FROM cohort_daily c
              WHERE c.model_id = m.id ORDER BY c.day DESC LIMIT 1
            ) latest ON true
            """
                + f.where()
                + " ORDER BY m.source, m.model LIMIT :limit OFFSET :offset")
        .params(f.params())
        .param("limit", page.size())
        .param("offset", page.offset())
        .query(
            (rs, i) ->
                new ModelItem(
                    rs.getInt("id"),
                    rs.getString("source"),
                    rs.getString("model"),
                    rs.getString("media"),
                    nullableLong(rs, "capacity_bytes"),
                    rs.getLong("drive_count")))
        .list();
  }

  public long countModels(String source, String media) {
    Filter f = modelFilter(source, media);
    return jdbc.sql("SELECT count(*) FROM drive_model m" + f.where())
        .params(f.params())
        .query(Long.class)
        .single();
  }

  private static Filter modelFilter(String source, String media) {
    Filter f = new Filter();
    if (source != null) {
      f.and("m.source = :source", "source", source);
    }
    if (media != null) {
      f.and("m.media = :media", "media", media);
    }
    return f;
  }

  /** The id of a model, if it exists. */
  public Optional<Integer> modelId(Source source, String model) {
    return jdbc.sql("SELECT id FROM drive_model WHERE source = :source AND model = :model")
        .param("source", source.id())
        .param("model", model)
        .query(Integer.class)
        .optional();
  }

  // ------------------------------------------------------------------ cohorts

  /** Drive-days and failures of one model per period; periods without drive-days are omitted. */
  public List<PeriodTotals> cohortPeriods(int modelId, Window window, Granularity granularity) {
    return jdbc.sql(
            "SELECT date_trunc('"
                + granularity.id()
                + "', c.day::timestamp)::date AS period_start,"
                + """
                       sum(c.drive_count)::bigint AS drive_days,
                       sum(c.failures)::bigint AS failures
                FROM cohort_daily c
                WHERE c.model_id = :modelId AND c.day BETWEEN :from AND :to
                GROUP BY 1
                HAVING sum(c.drive_count) > 0
                ORDER BY 1
                """)
        .param("modelId", modelId)
        .param("from", window.from())
        .param("to", window.to())
        .query(
            (rs, i) ->
                new PeriodTotals(
                    rs.getObject("period_start", LocalDate.class),
                    rs.getLong("drive_days"),
                    rs.getLong("failures")))
        .list();
  }

  /** Totals of every model of a source with data in the window (input to compare). */
  public List<ModelWindowTotals> modelWindowTotals(Source source, Window window) {
    return jdbc.sql(
            """
            WITH win AS (
              SELECT c.model_id, c.day, c.drive_count, c.failures
              FROM cohort_daily c JOIN drive_model m ON m.id = c.model_id
              WHERE m.source = :source AND c.day BETWEEN :from AND :to
            ), last_day AS (
              SELECT DISTINCT ON (model_id) model_id, drive_count
              FROM win ORDER BY model_id, day DESC
            )
            SELECT m.model,
                   sum(w.drive_count)::bigint AS drive_days,
                   sum(w.failures)::bigint AS failures,
                   l.drive_count AS last_day_drive_count
            FROM win w
            JOIN drive_model m ON m.id = w.model_id
            JOIN last_day l ON l.model_id = w.model_id
            GROUP BY m.model, l.drive_count
            ORDER BY m.model
            """)
        .param("source", source.id())
        .param("from", window.from())
        .param("to", window.to())
        .query(
            (rs, i) ->
                new ModelWindowTotals(
                    rs.getString("model"),
                    rs.getLong("drive_days"),
                    rs.getLong("failures"),
                    rs.getLong("last_day_drive_count")))
        .list();
  }

  /** Distinct drives seen in the window, plus drive-days and failures of all models. */
  public FleetTotals fleetTotals(Source source, Window window) {
    long drives =
        jdbc.sql(
                """
                SELECT count(*) FROM drive d
                WHERE d.source = :source AND d.first_seen <= :to AND d.last_seen >= :from
                """)
            .param("source", source.id())
            .param("from", window.from())
            .param("to", window.to())
            .query(Long.class)
            .single();
    return jdbc.sql(
            """
            SELECT COALESCE(sum(c.drive_count), 0)::bigint AS drive_days,
                   COALESCE(sum(c.failures), 0)::bigint AS failures
            FROM cohort_daily c JOIN drive_model m ON m.id = c.model_id
            WHERE m.source = :source AND c.day BETWEEN :from AND :to
            """)
        .param("source", source.id())
        .param("from", window.from())
        .param("to", window.to())
        .query((rs, i) -> new FleetTotals(drives, rs.getLong("drive_days"), rs.getLong("failures")))
        .single();
  }

  // ------------------------------------------------------------------ SMART

  /** p50, p95 and non-zero share of one attribute's raw value over the model's sampled drives. */
  public List<SmartTrendRow> smartTrend(
      Source source, int modelId, int attr, Window window, Granularity granularity) {
    return jdbc.sql(
            "SELECT date_trunc('"
                + granularity.id()
                + "', s.day::timestamp)::date AS period_start,"
                + """
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY s.raw_value) AS p50,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY s.raw_value) AS p95,
                       avg(CASE WHEN s.raw_value > 0 THEN 1.0 ELSE 0.0 END)::double precision
                         AS nonzero_share,
                       count(DISTINCT s.drive_id) AS n_drives
                FROM smart_daily s
                JOIN drive d ON d.source = s.source AND d.drive_id = s.drive_id
                WHERE s.source = :source AND d.model_id = :modelId AND d.sampled
                  AND s.attr = :attr AND s.day BETWEEN :from AND :to
                GROUP BY 1
                ORDER BY 1
                """)
        .param("source", source.id())
        .param("modelId", modelId)
        .param("attr", attr)
        .param("from", window.from())
        .param("to", window.to())
        .query(
            (rs, i) ->
                new SmartTrendRow(
                    rs.getObject("period_start", LocalDate.class),
                    nullableDouble(rs, "p50"),
                    nullableDouble(rs, "p95"),
                    rs.getDouble("nonzero_share"),
                    rs.getLong("n_drives")))
        .list();
  }

  // ------------------------------------------------------------------ failed drives

  public long countFailedDrives(int modelId, Window window) {
    return jdbc.sql(
            """
            SELECT count(*) FROM drive d
            WHERE d.model_id = :modelId AND d.failed_on BETWEEN :from AND :to
            """)
        .param("modelId", modelId)
        .param("from", window.from())
        .param("to", window.to())
        .query(Long.class)
        .single();
  }

  /**
   * Failed drives ordered by {@code failed_on, drive_id}; {@code age_days = failed_on -
   * first_seen}; {@code last_smart} holds the raw values recorded on {@code failed_on}.
   */
  public List<FailedDrive> failedDrives(
      Source source, int modelId, Window window, PageParams page) {
    Map<String, FailedDriveBuilder> byDrive = new LinkedHashMap<>();
    jdbc.sql(
            """
            WITH page AS (
              SELECT d.drive_id, d.failed_on, (d.failed_on - d.first_seen) AS age_days
              FROM drive d
              WHERE d.model_id = :modelId AND d.failed_on BETWEEN :from AND :to
              ORDER BY d.failed_on, d.drive_id
              LIMIT :limit OFFSET :offset
            )
            SELECT p.drive_id, p.failed_on, p.age_days, s.attr, s.raw_value
            FROM page p
            LEFT JOIN smart_daily s
              ON s.source = :source AND s.drive_id = p.drive_id AND s.day = p.failed_on
            ORDER BY p.failed_on, p.drive_id, s.attr
            """)
        .param("source", source.id())
        .param("modelId", modelId)
        .param("from", window.from())
        .param("to", window.to())
        .param("limit", page.size())
        .param("offset", page.offset())
        .query(
            (RowCallbackHandler)
                rs -> {
                  String driveId = rs.getString("drive_id");
                  FailedDriveBuilder b = byDrive.get(driveId);
                  if (b == null) {
                    b =
                        new FailedDriveBuilder(
                            driveId,
                            rs.getObject("failed_on", LocalDate.class),
                            rs.getInt("age_days"));
                    byDrive.put(driveId, b);
                  }
                  int attr = rs.getInt("attr");
                  if (!rs.wasNull()) {
                    b.lastSmart.put(Integer.toString(attr), nullableDouble(rs, "raw_value"));
                  }
                });
    List<FailedDrive> out = new ArrayList<>(byDrive.size());
    for (FailedDriveBuilder b : byDrive.values()) {
      out.add(new FailedDrive(b.driveId, b.failedOn, b.ageDays, b.lastSmart));
    }
    return out;
  }

  private static final class FailedDriveBuilder {
    final String driveId;
    final LocalDate failedOn;
    final int ageDays;
    final Map<String, Double> lastSmart = new LinkedHashMap<>();

    FailedDriveBuilder(String driveId, LocalDate failedOn, int ageDays) {
      this.driveId = driveId;
      this.failedOn = failedOn;
      this.ageDays = ageDays;
    }
  }

  // ------------------------------------------------------------------ alerts

  public List<AlertItem> alerts(String status, String source) {
    Filter f = new Filter();
    if (status != null) {
      f.and("a.status = :status", "status", status);
    }
    if (source != null) {
      f.and("m.source = :source", "source", source);
    }
    return jdbc.sql(
            """
            SELECT a.id, a.model_id, m.source, m.model, a.opened_at, a.window_start,
                   a.window_end, a.baseline_afr, a.current_afr, a.rate_ratio, a.p_value,
                   a.status, a.resolved_at
            FROM alert a JOIN drive_model m ON m.id = a.model_id
            """
                + f.where()
                + " ORDER BY a.opened_at DESC, a.id")
        .params(f.params())
        .query(
            (rs, i) ->
                new AlertItem(
                    rs.getObject("id", UUID.class),
                    rs.getInt("model_id"),
                    rs.getString("source"),
                    rs.getString("model"),
                    rs.getObject("opened_at", OffsetDateTime.class),
                    rs.getObject("window_start", LocalDate.class),
                    rs.getObject("window_end", LocalDate.class),
                    rs.getDouble("baseline_afr"),
                    rs.getDouble("current_afr"),
                    rs.getDouble("rate_ratio"),
                    rs.getDouble("p_value"),
                    rs.getString("status"),
                    rs.getObject("resolved_at", OffsetDateTime.class)))
        .list();
  }

  // ------------------------------------------------------------------ helpers

  /** AND-ed conditions built from fixed SQL fragments with named bind parameters. */
  private static final class Filter {
    private final List<String> conditions = new ArrayList<>();
    private final Map<String, Object> params = new LinkedHashMap<>();

    void and(String condition, String name, Object value) {
      conditions.add(condition);
      params.put(name, value);
    }

    String where() {
      return conditions.isEmpty() ? "" : " WHERE " + String.join(" AND ", conditions);
    }

    Map<String, Object> params() {
      return params;
    }
  }

  private static Long nullableLong(ResultSet rs, String column) throws SQLException {
    long v = rs.getLong(column);
    return rs.wasNull() ? null : v;
  }

  private static Double nullableDouble(ResultSet rs, String column) throws SQLException {
    double v = rs.getDouble(column);
    return rs.wasNull() ? null : v;
  }
}
