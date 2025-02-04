# sbir-road-lod2-evaluation-tool

## 定量評価

### QuantEvalate.py

| 設定値名     |  例         | 説明                                     |
| ------------ | ---- | ---------- |
| `shp_dir_pred`     |  `./sample/pred_hiroshima_5city` | 推論作成されたLOD2のvectorzied(.shp)データのディレクトリ   |
| `shp_dir_true` |  `./sample/true_hiroshima_v2.4`  | 正解LOD2データのディレクトリ |
| `epsg` |  `None`  | 正解LOD2データのepsgが直交座標系では無い場合、仙台なら`6678`などを設定する |
| `city` |  `hiroshima`  | 都市名を入力 |

## 定性評価

### QualEvalate.py

| 設定値名     |  例         | 説明                                     |
| ------------ | ---- | ---------- |
| `pred_name`     |  `pred_hiroshima_5city` | 推論作成されたLOD2のvectorzied(.shp)データのフォルダ名   |
| `true_name` |  `kaga_shp_lod2_add_intersection`  | 正解LOD2データのフォルダ名 |
| `city` |  `hiroshima`  | 都市名を入力 |
