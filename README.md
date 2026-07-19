# Repository Coverage



| Name                                                     |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| agents/city\_context.py                                  |        9 |        9 |        0 |        0 |      0% |     13-44 |
| agents/lambda\_proxy/handler.py                          |       70 |       21 |       24 |        3 |     70% |69, 74-75, 84, 88, 106-109, 119-122, 129-138 |
| agents/lambda\_proxy/test\_handler.py                    |       51 |        1 |        6 |        1 |     96% |        25 |
| agents/scores\_match.py                                  |       93 |        1 |       42 |        1 |     99% |       239 |
| agents/tools/explain\_restaurant/handler.py              |      104 |       19 |       44 |        8 |     78% |28, 30, 36, 38, 49-50, 59-60, 160, 167, 249-255, 284-\>290, 287-288 |
| agents/tools/find\_inspection\_records/handler.py        |       59 |        1 |       20 |        1 |     97% |       136 |
| agents/tools/find\_restaurants/chicago\_neighborhoods.py |        4 |        0 |        0 |        0 |    100% |           |
| agents/tools/find\_restaurants/handler.py                |      113 |        7 |       36 |        2 |     94% |213-215, 260-271, 337 |
| agents/tools/find\_restaurants/la\_neighborhoods.py      |        4 |        0 |        0 |        0 |    100% |           |
| agents/tools/find\_restaurants/nyc\_neighborhoods.py     |        4 |        0 |        0 |        0 |    100% |           |
| agents/tools/find\_reviews/handler.py                    |       25 |        0 |        6 |        0 |    100% |           |
| agents/tools/food\_safety\_info/handler.py               |       44 |        2 |       16 |        4 |     90% |410, 436, 442-\>445, 450-\>447 |
| agents/tools/get\_safety\_score/handler.py               |       72 |        2 |       20 |        2 |     96% |  149, 194 |
| agents/tools/get\_safety\_score/sagemaker\_stub.py       |       68 |       17 |       20 |        0 |     76% |   306-355 |
| agents/tools/look\_up\_establishment/handler.py          |       86 |       10 |       24 |        4 |     87% |51, 53, 59, 61, 71-72, 81-82, 262-263 |
| agents/tools/visualize\_data/handler.py                  |      158 |       69 |       58 |        4 |     54% |51-55, 68, 114, 223-259, 273-285, 290-301, 306-311, 325-342, 356, 440 |
| src/foodsafety/\_\_init\_\_.py                           |        0 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/audit/\_\_init\_\_.py                     |        1 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/audit/config.py                           |       36 |        2 |        0 |        0 |     94% |  196, 200 |
| src/foodsafety/audit/fairness.py                         |      173 |        4 |       48 |        6 |     95% |39, 78, 82-\>84, 254, 304-\>302, 343 |
| src/foodsafety/audit/frame.py                            |       38 |        1 |       10 |        2 |     94% |89, 92-\>94 |
| src/foodsafety/audit/mitigation.py                       |       32 |        2 |        6 |        2 |     89% |    46, 58 |
| src/foodsafety/audit/report.py                           |       73 |       14 |       28 |        6 |     76% |54, 58, 66, 77, 81, 86-101 |
| src/foodsafety/config.py                                 |       43 |        4 |        4 |        1 |     85% |     34-37 |
| src/foodsafety/data/\_\_init\_\_.py                      |        0 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/data/labels.py                            |       65 |        0 |       16 |        1 |     99% | 199-\>201 |
| src/foodsafety/explain/\_\_init\_\_.py                   |        0 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/explain/feature\_labels.py                |       10 |        1 |        0 |        0 |     90% |       160 |
| src/foodsafety/explain/shap\_drivers.py                  |       99 |       12 |       36 |        8 |     82% |75-78, 101, 108, 125, 189-\>191, 194-\>198, 200-201, 245, 255-256 |
| src/foodsafety/features/\_\_init\_\_.py                  |        0 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/features/build.py                         |       35 |        4 |       14 |        7 |     78% |98, 102, 109, 118-\>120, 120-\>122, 122-\>124, 131 |
| src/foodsafety/features/building\_features.py            |       89 |       28 |       32 |        2 |     67% |179, 199, 228-282 |
| src/foodsafety/features/complaint\_features.py           |      106 |        3 |       20 |        2 |     96% |139-140, 292 |
| src/foodsafety/features/inspection\_features.py          |       66 |        1 |        6 |        1 |     97% |        92 |
| src/foodsafety/features/keyword\_flags.py                |       11 |        0 |        2 |        0 |    100% |           |
| src/foodsafety/features/license\_features.py             |       37 |        2 |       20 |        2 |     93% |    66, 99 |
| src/foodsafety/features/license\_history\_features.py    |       25 |        0 |        2 |        0 |    100% |           |
| src/foodsafety/features/temporal\_features.py            |       20 |        0 |        2 |        0 |    100% |           |
| src/foodsafety/features/text\_features.py                |       24 |        1 |        2 |        1 |     92% |        85 |
| src/foodsafety/features/violation\_labels.py             |       27 |        1 |        2 |        1 |     93% |        94 |
| src/foodsafety/ingest.py                                 |       57 |        0 |       24 |        0 |    100% |           |
| src/foodsafety/io/\_\_init\_\_.py                        |        0 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/io/cache.py                               |       21 |        3 |        8 |        3 |     79% |46, 50, 59 |
| src/foodsafety/io/soda.py                                |      107 |       11 |       56 |       11 |     87% |65-\>89, 83-84, 157-158, 163-\>211, 177, 201, 216, 221, 261, 296, 301 |
| src/foodsafety/io/storage.py                             |       74 |        2 |       12 |        3 |     94% |51-52, 72-\>exit, 74-\>exit |
| src/foodsafety/models/\_\_init\_\_.py                    |        0 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/models/baseline.py                        |       21 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/models/evaluate.py                        |      108 |        3 |       20 |        3 |     95% |72, 122, 275 |
| src/foodsafety/models/xgb.py                             |       33 |        0 |       10 |        0 |    100% |           |
| src/foodsafety/serve/\_\_init\_\_.py                     |        0 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/serve/predict\_batch.py                   |      126 |       13 |       24 |        7 |     87% |129, 213, 215, 254, 331-333, 345-346, 351-352, 390-391, 394-\>420 |
| src/foodsafety/tracking.py                               |       28 |       28 |        0 |        0 |      0% |     18-92 |
| src/foodsafety/utils/\_\_init\_\_.py                     |        0 |        0 |        0 |        0 |    100% |           |
| src/foodsafety/utils/geo.py                              |       23 |        0 |        4 |        0 |    100% |           |
| src/foodsafety/utils/time.py                             |       56 |        2 |       16 |        2 |     94% |133, 150-\>141, 168 |
| **TOTAL**                                                | **2628** |  **301** |  **740** |  **101** | **86%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://github.com/food-safety-intelligence/food-safety-intelligence/raw/python-coverage-comment-action-data/badge.svg)](https://github.com/food-safety-intelligence/food-safety-intelligence/tree/python-coverage-comment-action-data)

This is the one to use if your repository is private or if you don't want to customize anything.



## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.