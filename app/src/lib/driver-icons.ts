import {
  AlertOctagon,
  AlertTriangle,
  Bug,
  CalendarClock,
  CalendarDays,
  CalendarX,
  ClipboardList,
  Clock,
  Droplet,
  Hand,
  History,
  MapPin,
  ShieldAlert,
  Split,
  Sprout,
  Store,
  Thermometer,
  UtensilsCrossed,
  XCircle,
  type LucideIcon,
} from "lucide-react";

/**
 * Map a model feature name to a lucide icon that visually hints at its
 * topic. Used by DriverList — the icon replaces the abstract rank number
 * with something a reader can parse at a glance.
 *
 * Matching is prefix-based for the keyword-flag family (`flag_kw_<topic>`),
 * and exact for the canonical 26 features. Unknown features fall back to
 * a generic clipboard icon so the layout still renders.
 */

const EXACT: Record<string, LucideIcon> = {
  prior_inspections: ClipboardList,
  prior_fails: XCircle,
  prior_priority_violations: AlertTriangle,
  prior_core_violations: AlertOctagon,
  prior_fail_or_priority_events: AlertTriangle,
  days_since_last_inspection: CalendarClock,
  days_since_last_fail: CalendarX,
  temporal_month: CalendarDays,
  temporal_quarter: CalendarDays,
  license_age_days: History,
  license_n_history_rows: History,
  static_facility_type: UtensilsCrossed,
  static_risk_tier: ShieldAlert,
  static_zip: MapPin,
};

// flag_kw_* family — keyed by the substring after the prefix.
const KW: Array<[RegExp, LucideIcon]> = [
  [/temp/, Thermometer],
  [/(rodent|vermin|pest|rat|mouse)/, Bug],
  [/(raw|chicken|meat|poultry)/, UtensilsCrossed],
  [/(cross[-_ ]?contam|cross)/, Split],
  [/(expired|expir|date)/, Clock],
  [/(soap|towel|handwash|hand[-_ ]?wash|wash)/, Hand],
  [/(sewage|sewer|drain|leak|water)/, Droplet],
  [/(mold|mildew)/, Sprout],
  [/(facility|kitchen|restaurant|food)/, Store],
];

export function iconForFeature(feature: string): LucideIcon {
  if (feature in EXACT) return EXACT[feature];
  if (feature.startsWith("flag_kw_")) {
    const topic = feature.slice("flag_kw_".length).toLowerCase();
    for (const [re, icon] of KW) {
      if (re.test(topic)) return icon;
    }
    return AlertTriangle;
  }
  return ClipboardList;
}
