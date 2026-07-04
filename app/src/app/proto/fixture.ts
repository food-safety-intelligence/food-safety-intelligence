// AUTO-GENERATED throwaway fixture (extract_fixture.py) — real 0.5.0 data.
import type { InspectionEvent, RestaurantScore } from "@/lib/scores";

export interface ProtoCase { kind: string; restaurant: RestaurantScore; history: InspectionEvent[]; }

export const POP_MEDIAN = 0.0414869524538517;

export const PROTO_CASES: ProtoCase[] = [
  {
    "kind": "worsening",
    "restaurant": {
      "license_id": "1841985",
      "dba_name": "A.P. DELI RESTAURANT GROUP, INC.",
      "address": "10758 S MICHIGAN AVE",
      "neighborhood": "",
      "zip": "",
      "facility_type": "Restaurant",
      "lat": 41.6981699973446,
      "lon": -87.62102419675304,
      "risk_score": 0.23498722910881042,
      "risk_tier": "Elevated",
      "trend_slope": 0.001117468653110868,
      "top_drivers": [
        {
          "feature": "prior_complaint_inspections",
          "value": "24",
          "shap": 1.2268,
          "label": "24 prior complaint-driven inspections"
        },
        {
          "feature": "license_age_days",
          "value": "5192.0",
          "shap": -0.5779,
          "label": "License is 5192 days old"
        },
        {
          "feature": "was_fail",
          "value": "0",
          "shap": -0.51,
          "label": "Passed the current inspection"
        },
        {
          "feature": "temporal_month",
          "value": "12",
          "shap": 0.4145,
          "label": "Anchored in month 12"
        },
        {
          "feature": "n_priority_this_inspection",
          "value": "0",
          "shap": -0.3409,
          "label": "0 priority violations at this inspection"
        }
      ],
      "percentile_rank": 98.55636933237373
    },
    "history": [
      {
        "date": "2025-12-24",
        "type": "Canvass Re-Inspection",
        "result": "Pass",
        "headline": "",
        "score": 0.2
      },
      {
        "date": "2025-12-24",
        "type": "Canvass",
        "result": "Out of Business",
        "headline": "",
        "score": 0.2
      },
      {
        "date": "2025-12-19",
        "type": "Canvass",
        "result": "Fail",
        "headline": "22. PROPER COLD HOLDING TEMPERATURES",
        "score": 0.645
      },
      {
        "date": "2025-10-09",
        "type": "Complaint Re-Inspection",
        "result": "Pass",
        "headline": "55. PHYSICAL FACILITIES INSTALLED, MAINTAINED & CLEAN",
        "score": 0.227
      },
      {
        "date": "2025-10-02",
        "type": "Complaint",
        "result": "Fail",
        "headline": "37. FOOD PROPERLY LABELED; ORIGINAL CONTAINER",
        "score": 0.5469
      },
      {
        "date": "2025-04-02",
        "type": "Canvass Re-Inspection",
        "result": "Pass",
        "headline": "47. FOOD & NON-FOOD CONTACT SURFACES CLEANABLE, PROPERLY DESIGNED, CONSTRUCTED & USED",
        "score": 0.1191
      },
      {
        "date": "2025-03-26",
        "type": "Canvass",
        "result": "Fail",
        "headline": "37. FOOD PROPERLY LABELED; ORIGINAL CONTAINER",
        "score": 0.1551
      },
      {
        "date": "2024-07-19",
        "type": "Complaint Re-Inspection",
        "result": "Pass",
        "headline": "45. SINGLE-USE/SINGLE-SERVICE ARTICLES: PROPERLY STORED & USED",
        "score": 0.1601
      },
      {
        "date": "2024-07-10",
        "type": "Complaint",
        "result": "Fail",
        "headline": "38. INSECTS, RODENTS, & ANIMALS NOT PRESENT",
        "score": 0.3478
      },
      {
        "date": "2023-12-01",
        "type": "Canvass Re-Inspection",
        "result": "Pass",
        "headline": "",
        "score": 0.1666
      },
      {
        "date": "2023-11-17",
        "type": "Canvass",
        "result": "Fail",
        "headline": "40. PERSONAL CLEANLINESS",
        "score": 0.4105
      },
      {
        "date": "2022-06-16",
        "type": "Canvass Re-Inspection",
        "result": "Pass w/ Conditions",
        "headline": "3. MANAGEMENT, FOOD EMPLOYEE AND CONDITIONAL EMPLOYEE; KNOWLEDGE, RESPONSIBILITIES AND REPORTING",
        "score": 0.175
      },
      {
        "date": "2022-06-09",
        "type": "Canvass",
        "result": "Fail",
        "headline": "3. MANAGEMENT, FOOD EMPLOYEE AND CONDITIONAL EMPLOYEE; KNOWLEDGE, RESPONSIBILITIES AND REPORTING",
        "score": 0.2202
      },
      {
        "date": "2021-12-15",
        "type": "Complaint Re-Inspection",
        "result": "Pass",
        "headline": "57. ALL FOOD EMPLOYEES HAVE FOOD HANDLER TRAINING",
        "score": 0.3649
      },
      {
        "date": "2021-12-08",
        "type": "Complaint",
        "result": "Fail",
        "headline": "22. PROPER COLD HOLDING TEMPERATURES",
        "score": 0.5611
      },
      {
        "date": "2021-11-15",
        "type": "Complaint Re-Inspection",
        "result": "Pass",
        "headline": "41. WIPING CLOTHS: PROPERLY USED & STORED",
        "score": 0.2742
      },
      {
        "date": "2021-11-04",
        "type": "Complaint",
        "result": "Fail",
        "headline": "10. ADEQUATE HANDWASHING SINKS PROPERLY SUPPLIED AND ACCESSIBLE",
        "score": 0.5868
      },
      {
        "date": "2021-06-21",
        "type": "Complaint Re-Inspection",
        "result": "Pass",
        "headline": "49. NON-FOOD/FOOD CONTACT SURFACES CLEAN",
        "score": 0.2144
      },
      {
        "date": "2021-06-09",
        "type": "Short Form Complaint",
        "result": "Fail",
        "headline": "1. PERSON IN CHARGE PRESENT, DEMONSTRATES KNOWLEDGE, AND PERFORMS DUTIES",
        "score": 0.3779
      },
      {
        "date": "2021-04-26",
        "type": "Canvass Re-Inspection",
        "result": "Pass",
        "headline": "49. NON-FOOD/FOOD CONTACT SURFACES CLEAN",
        "score": 0.1125
      },
      {
        "date": "2021-04-19",
        "type": "Canvass",
        "result": "Fail",
        "headline": "5. PROCEDURES FOR RESPONDING TO VOMITING AND DIARRHEAL EVENTS",
        "score": 0.4304
      },
      {
        "date": "2020-02-21",
        "type": "Canvass",
        "result": "Pass",
        "headline": "51. PLUMBING INSTALLED; PROPER BACKFLOW DEVICES",
        "score": 0.1223
      },
      {
        "date": "2019-06-07",
        "type": "Complaint Re-Inspection",
        "result": "Pass w/ Conditions",
        "headline": "5. PROCEDURES FOR RESPONDING TO VOMITING AND DIARRHEAL EVENTS",
        "score": 0.2137
      },
      {
        "date": "2019-05-31",
        "type": "Complaint",
        "result": "Fail",
        "headline": "5. PROCEDURES FOR RESPONDING TO VOMITING AND DIARRHEAL EVENTS",
        "score": 0.4797
      },
      {
        "date": "2019-02-08",
        "type": "Canvass Re-Inspection",
        "result": "Pass w/ Conditions",
        "headline": "3. MANAGEMENT, FOOD EMPLOYEE AND CONDITIONAL EMPLOYEE; KNOWLEDGE, RESPONSIBILITIES AND REPORTING",
        "score": 0.325
      },
      {
        "date": "2019-01-28",
        "type": "Canvass",
        "result": "Fail",
        "headline": "3. MANAGEMENT, FOOD EMPLOYEE AND CONDITIONAL EMPLOYEE; KNOWLEDGE, RESPONSIBILITIES AND REPORTING",
        "score": 0.7412
      },
      {
        "date": "2017-11-01",
        "type": "Canvass Re-Inspection",
        "result": "Pass",
        "headline": "30. FOOD IN ORIGINAL CONTAINER, PROPERLY LABELED: CUSTOMER ADVISORY POSTED AS NEEDED",
        "score": null
      },
      {
        "date": "2017-10-17",
        "type": "Canvass",
        "result": "Fail",
        "headline": "18. NO EVIDENCE OF RODENT OR INSECT OUTER OPENINGS PROTECTED/RODENT PROOFED, A WRITTEN LOG SHALL BE \u2026",
        "score": null
      },
      {
        "date": "2016-05-24",
        "type": "Canvass Re-Inspection",
        "result": "Pass",
        "headline": "36. LIGHTING: REQUIRED MINIMUM FOOT-CANDLES OF LIGHT PROVIDED, FIXTURES SHIELDED",
        "score": null
      },
      {
        "date": "2016-05-17",
        "type": "Canvass",
        "result": "Fail",
        "headline": "18. NO EVIDENCE OF RODENT OR INSECT OUTER OPENINGS PROTECTED/RODENT PROOFED, A WRITTEN LOG SHALL BE \u2026",
        "score": null
      }
    ]
  },
  {
    "kind": "improving",
    "restaurant": {
      "license_id": "2938829",
      "dba_name": "TAQUERIA & TAMALES EL BUEN GUSTO",
      "address": "6012 W FULLERTON AVE ",
      "neighborhood": "",
      "zip": "",
      "facility_type": "Restaurant",
      "lat": 41.92392648360924,
      "lon": -87.77632683025247,
      "risk_score": 0.13035522401332855,
      "risk_tier": "Elevated",
      "trend_slope": -0.011935315065682973,
      "top_drivers": [
        {
          "feature": "license_age_days",
          "value": "-14.0",
          "shap": 0.674,
          "label": "License is -14 days old"
        },
        {
          "feature": "was_fail",
          "value": "0",
          "shap": -0.616,
          "label": "Passed the current inspection"
        },
        {
          "feature": "temporal_month",
          "value": "12",
          "shap": 0.4966,
          "label": "Anchored in month 12"
        },
        {
          "feature": "n_priority_this_inspection",
          "value": "0",
          "shap": -0.3496,
          "label": "0 priority violations at this inspection"
        },
        {
          "feature": "n_core_this_inspection",
          "value": "0",
          "shap": -0.3038,
          "label": "0 core violations at this inspection"
        }
      ],
      "percentile_rank": 93.59891621861902
    },
    "history": [
      {
        "date": "2025-03-14",
        "type": "Canvass",
        "result": "Out of Business",
        "headline": "",
        "score": null
      },
      {
        "date": "2024-12-11",
        "type": "Non-Inspection",
        "result": "No Entry",
        "headline": "",
        "score": null
      },
      {
        "date": "2024-11-01",
        "type": "Non-Inspection",
        "result": "No Entry",
        "headline": "",
        "score": null
      },
      {
        "date": "2023-12-15",
        "type": "License Re-Inspection",
        "result": "Pass",
        "headline": "",
        "score": 0.1236
      },
      {
        "date": "2023-12-11",
        "type": "License Re-Inspection",
        "result": "Fail",
        "headline": "38. INSECTS, RODENTS, & ANIMALS NOT PRESENT",
        "score": 0.333
      },
      {
        "date": "2023-12-04",
        "type": "License Re-Inspection",
        "result": "Fail",
        "headline": "38. INSECTS, RODENTS, & ANIMALS NOT PRESENT",
        "score": 0.2379
      },
      {
        "date": "2023-11-24",
        "type": "License Re-Inspection",
        "result": "Fail",
        "headline": "38. INSECTS, RODENTS, & ANIMALS NOT PRESENT",
        "score": 0.4613
      },
      {
        "date": "2023-11-16",
        "type": "License",
        "result": "Fail",
        "headline": "2. CITY OF CHICAGO FOOD SERVICE SANITATION CERTIFICATE",
        "score": 0.515
      }
    ]
  },
  {
    "kind": "stable",
    "restaurant": {
      "license_id": "2694886",
      "dba_name": "DASH OF SALT AND PEPPER",
      "address": "2201 N LINCOLN AVE",
      "neighborhood": "",
      "zip": "",
      "facility_type": "Restaurant",
      "lat": 41.92205611581004,
      "lon": -87.64381082771762,
      "risk_score": 0.046285152435302734,
      "risk_tier": "Moderate",
      "trend_slope": -2.2672643312084652e-05,
      "top_drivers": [
        {
          "feature": "was_fail",
          "value": "0",
          "shap": -0.6647,
          "label": "Passed the current inspection"
        },
        {
          "feature": "n_core_this_inspection",
          "value": "1",
          "shap": -0.2389,
          "label": "1 core violations at this inspection"
        },
        {
          "feature": "static_inspection_type",
          "value": "Canvass",
          "shap": -0.1292,
          "label": "Inspection type: Canvass"
        },
        {
          "feature": "days_since_last_fail",
          "value": "2030.0",
          "shap": -0.1058,
          "label": "Last fail was 2030 days ago"
        },
        {
          "feature": "license_age_days",
          "value": "2022.0",
          "shap": 0.0962,
          "label": "License is 2022 days old"
        }
      ],
      "percentile_rank": 55.96291435586978
    },
    "history": [
      {
        "date": "2025-08-20",
        "type": "Canvass",
        "result": "Pass",
        "headline": "16. FOOD-CONTACT SURFACES: CLEANED & SANITIZED",
        "score": 0.046
      },
      {
        "date": "2024-12-04",
        "type": "Canvass",
        "result": "Pass",
        "headline": "40. PERSONAL CLEANLINESS",
        "score": 0.0684
      },
      {
        "date": "2024-01-12",
        "type": "Canvass",
        "result": "Pass",
        "headline": "41. WIPING CLOTHS: PROPERLY USED & STORED",
        "score": 0.0953
      },
      {
        "date": "2023-08-15",
        "type": "Canvass",
        "result": "Pass",
        "headline": "47. FOOD & NON-FOOD CONTACT SURFACES CLEANABLE, PROPERLY DESIGNED, CONSTRUCTED & USED",
        "score": 0.0676
      },
      {
        "date": "2022-08-16",
        "type": "Complaint",
        "result": "Pass",
        "headline": "37. FOOD PROPERLY LABELED; ORIGINAL CONTAINER",
        "score": 0.0742
      },
      {
        "date": "2021-02-25",
        "type": "Canvass",
        "result": "Pass w/ Conditions",
        "headline": "25. CONSUMER ADVISORY PROVIDED FOR RAW/UNDERCOOKED FOOD",
        "score": 0.0443
      },
      {
        "date": "2020-01-31",
        "type": "License Re-Inspection",
        "result": "Pass w/ Conditions",
        "headline": "3. MANAGEMENT, FOOD EMPLOYEE AND CONDITIONAL EMPLOYEE; KNOWLEDGE, RESPONSIBILITIES AND REPORTING",
        "score": 0.0575
      },
      {
        "date": "2020-01-29",
        "type": "License",
        "result": "Fail",
        "headline": "3. MANAGEMENT, FOOD EMPLOYEE AND CONDITIONAL EMPLOYEE; KNOWLEDGE, RESPONSIBILITIES AND REPORTING",
        "score": 0.1722
      },
      {
        "date": "2019-10-17",
        "type": "License",
        "result": "Not Ready",
        "headline": "",
        "score": null
      }
    ]
  },
  {
    "kind": "high_risk",
    "restaurant": {
      "license_id": "2699095",
      "dba_name": "CHITOWN FUTBOL & SOCIAL",
      "address": "2343 S THROOP ST ",
      "neighborhood": "",
      "zip": "",
      "facility_type": "Restaurant",
      "lat": 41.84937722810732,
      "lon": -87.65847731791494,
      "risk_score": 0.39229273796081543,
      "risk_tier": "High",
      "trend_slope": 0.0002986080849759312,
      "top_drivers": [
        {
          "feature": "was_fail",
          "value": "1",
          "shap": 1.063,
          "label": "Failed the current inspection"
        },
        {
          "feature": "n_priority_this_inspection",
          "value": "2",
          "shap": 0.3725,
          "label": "2 priority violations at this inspection"
        },
        {
          "feature": "n_core_this_inspection",
          "value": "5",
          "shap": 0.1682,
          "label": "5 core violations at this inspection"
        },
        {
          "feature": "temporal_month",
          "value": "2",
          "shap": -0.1018,
          "label": "Anchored in month 2"
        },
        {
          "feature": "flag_kw_pest",
          "value": "True",
          "shap": 0.0814,
          "label": "Pest activity noted"
        }
      ],
      "percentile_rank": 99.42424114135726
    },
    "history": [
      {
        "date": "2023-02-16",
        "type": "Canvass Re-Inspection",
        "result": "Out of Business",
        "headline": "56. ADEQUATE VENTILATION & LIGHTING; DESIGNATED AREAS USED",
        "score": null
      },
      {
        "date": "2023-02-14",
        "type": "Canvass",
        "result": "Fail",
        "headline": "3. MANAGEMENT, FOOD EMPLOYEE AND CONDITIONAL EMPLOYEE; KNOWLEDGE, RESPONSIBILITIES AND REPORTING",
        "score": 0.4705
      },
      {
        "date": "2021-10-06",
        "type": "Canvass",
        "result": "Pass",
        "headline": "53. TOILET FACILITIES: PROPERLY CONSTRUCTED, SUPPLIED, & CLEANED",
        "score": 0.0956
      },
      {
        "date": "2020-10-01",
        "type": "Complaint Re-Inspection",
        "result": "Pass",
        "headline": "37. FOOD PROPERLY LABELED; ORIGINAL CONTAINER",
        "score": 0.1285
      },
      {
        "date": "2020-09-29",
        "type": "Complaint Re-Inspection",
        "result": "Fail",
        "headline": "10. ADEQUATE HANDWASHING SINKS PROPERLY SUPPLIED AND ACCESSIBLE",
        "score": 0.2192
      },
      {
        "date": "2020-09-24",
        "type": "Complaint",
        "result": "Fail",
        "headline": "10. ADEQUATE HANDWASHING SINKS PROPERLY SUPPLIED AND ACCESSIBLE",
        "score": 0.1712
      },
      {
        "date": "2020-01-23",
        "type": "License",
        "result": "Pass",
        "headline": "51. PLUMBING INSTALLED; PROPER BACKFLOW DEVICES",
        "score": 0.0844
      },
      {
        "date": "2020-01-07",
        "type": "License",
        "result": "Not Ready",
        "headline": "",
        "score": null
      }
    ]
  },
  {
    "kind": "few_points",
    "restaurant": {
      "license_id": "35960",
      "dba_name": "NITE CAP",
      "address": "5007-5009 W IRVING PARK RD ",
      "neighborhood": "",
      "zip": "",
      "facility_type": "Restaurant",
      "lat": 41.95324249980824,
      "lon": -87.75253198482571,
      "risk_score": 0.04165733605623245,
      "risk_tier": "Moderate",
      "trend_slope": -1.9440455188348934e-06,
      "top_drivers": [
        {
          "feature": "was_fail",
          "value": "0",
          "shap": -0.6272,
          "label": "Passed the current inspection"
        },
        {
          "feature": "temporal_month",
          "value": "12",
          "shap": 0.5985,
          "label": "Anchored in month 12"
        },
        {
          "feature": "license_age_days",
          "value": "4150.0",
          "shap": -0.4067,
          "label": "License is 4150 days old"
        },
        {
          "feature": "n_priority_this_inspection",
          "value": "0",
          "shap": -0.4065,
          "label": "0 priority violations at this inspection"
        },
        {
          "feature": "prior_complaint_inspections",
          "value": "0",
          "shap": -0.2919,
          "label": "0 prior complaint-driven inspections"
        }
      ],
      "percentile_rank": 50.26459506371449
    },
    "history": [
      {
        "date": "2023-06-22",
        "type": "Canvass",
        "result": "Out of Business",
        "headline": "",
        "score": null
      },
      {
        "date": "2022-12-21",
        "type": "Canvass",
        "result": "Pass",
        "headline": "47. FOOD & NON-FOOD CONTACT SURFACES CLEANABLE, PROPERLY DESIGNED, CONSTRUCTED & USED",
        "score": 0.0429
      },
      {
        "date": "2021-08-17",
        "type": "Canvass",
        "result": "Pass",
        "headline": "",
        "score": 0.0231
      },
      {
        "date": "2021-07-27",
        "type": "Non-Inspection",
        "result": "No Entry",
        "headline": "",
        "score": null
      },
      {
        "date": "2019-03-05",
        "type": "Canvass",
        "result": "Pass w/ Conditions",
        "headline": "3. MANAGEMENT, FOOD EMPLOYEE AND CONDITIONAL EMPLOYEE; KNOWLEDGE, RESPONSIBILITIES AND REPORTING",
        "score": 0.0419
      },
      {
        "date": "2017-02-21",
        "type": "Canvass",
        "result": "Not Ready",
        "headline": "",
        "score": null
      },
      {
        "date": "2016-09-02",
        "type": "Canvass",
        "result": "No Entry",
        "headline": "",
        "score": null
      },
      {
        "date": "2015-10-14",
        "type": "Canvass",
        "result": "No Entry",
        "headline": "",
        "score": null
      },
      {
        "date": "2014-07-28",
        "type": "Canvass",
        "result": "No Entry",
        "headline": "",
        "score": null
      },
      {
        "date": "2013-11-12",
        "type": "Canvass",
        "result": "No Entry",
        "headline": "",
        "score": null
      },
      {
        "date": "2010-09-16",
        "type": "Canvass",
        "result": "Pass",
        "headline": "32. FOOD AND NON-FOOD CONTACT SURFACES PROPERLY DESIGNED, CONSTRUCTED AND MAINTAINED",
        "score": null
      }
    ]
  }
] as ProtoCase[];
