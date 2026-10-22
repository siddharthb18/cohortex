package dev.cohortex.fleetapi.web;

import java.util.Set;

/** Telemetry sources and the SMART attributes kept for each in the serving tables (contracts §1). */
public enum Source {
  BACKBLAZE("backblaze", Set.of(5, 9, 12, 187, 188, 193, 194, 197, 198, 199, 240, 241, 242)),
  ALIBABA("alibaba", Set.of(5, 9, 12, 171, 172, 173, 174, 175, 187, 188, 194, 195, 199));

  private final String id;
  @SuppressWarnings("ImmutableEnumChecker") // always an unmodifiable Set.of(...)
  private final Set<Integer> keptSmartAttributes;

  Source(String id, Set<Integer> keptSmartAttributes) {
    this.id = id;
    this.keptSmartAttributes = keptSmartAttributes;
  }

  /** The value stored in the database and used in URLs. */
  public String id() {
    return id;
  }

  public boolean keepsSmartAttribute(int attr) {
    return keptSmartAttributes.contains(attr);
  }
}
