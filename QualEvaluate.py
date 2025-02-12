# -*- coding: utf-8 -*-
import sys
import os
from multiprocessing import Pool
import shutil
import pandas as pd
import shapefile
from shapely.geometry import shape as Shape
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.geometry.collection import GeometryCollection
import polyskel
from decimal import Decimal
import decimal
import gc
import sys


DIFF_DIST_REFERENCE = 1.75
EVALUATION_REFERENCE = 0.5
# 許容する最小エッジ長
TOLERANCE = 0.000000001


def truncate_coordinates(geom, precision=9):
    """
    Shapelyジオメトリオブジェクトの座標の小数点以下を指定桁数で切り捨て、
    かつ不要な0を削除する
    Args:
        geom: Shapelyジオメトリオブジェクト
        precision: 切り捨て桁数
    Returns:
        座標が切り捨てられ、かつ不要な0が削除されたShapelyジオメトリオブジェクト
    """

    def truncate_and_remove_zeros(x, precision):
        d = Decimal(x).quantize(Decimal(f"1e-{precision}"), rounding=decimal.ROUND_DOWN) # 切り捨て
        return d.normalize() # 0詰めを削除

    if geom.geom_type == 'Polygon':
        exterior = [(truncate_and_remove_zeros(x, precision), truncate_and_remove_zeros(y, precision)) for x, y in geom.exterior.coords]
        interiors = [[(truncate_and_remove_zeros(x, precision), truncate_and_remove_zeros(y, precision)) for x, y in interior.coords] for interior in geom.interiors]
        return Polygon(exterior, interiors)
    else:
        # 他のジオメトリタイプへの対応が必要な場合はここに処理を追加
        return geom

def read_road_pred(shp_path):
    """
    予測シェープファイル読み込み機能
    """
    
    def convert_class(set_class, set_intersec):
        """
        予測シェープファイルから正解シェープファイルのclass形式に変換
        """
        if set_class == 1:
            if set_intersec == 1:
                # 車道交差部
                return 1020
            else:
                # 車道部
                return 1000
        elif set_class == 2:
            # 歩道部
            return 2000
        elif set_class == 3:
            # 島部
            return 3000
        else:
            return set_class


    shx_path = shp_path[:-4] + ".shx"
    dbf_path = shp_path[:-4] + ".dbf"

    shp_file = open(shp_path.encode("utf-8"), "rb")
    shx_file = open(shx_path.encode("utf-8"), "rb")
    dbf_file = open(dbf_path.encode("utf-8"), "rb")

    data = []
    with shapefile.Reader(shp=shp_file, shx=shx_file, dbf=dbf_file, encoding='Shift-JIS') as sf:
        for sr in sf.iterShapeRecords(): 
            id = sr.record["lod1_id"]
            cls = sr.record["class"]
            intersec = sr.record["is_in_inte"]

            geom = Shape(sr.shape.__geo_interface__)
            #geom = truncate_coordinates(geom)

            data.append({
                "id" : id,
                "class": str(convert_class(cls, intersec)),
                "poly": geom
                })

    shp_file.close()
    shx_file.close()
    dbf_file.close()

    return data

def read_road_true(shp_path, encoding="Shift-JIS"):
    """
    正解シェープファイル読み込み機能
    """
    shx_path = shp_path[:-4] + ".shx"
    dbf_path = shp_path[:-4] + ".dbf"

    shp_file = open(shp_path.encode("utf-8"), "rb")
    shx_file = open(shx_path.encode("utf-8"), "rb")
    dbf_file = open(dbf_path.encode("utf-8"), "rb")

    data = []
    with shapefile.Reader(shp=shp_file, shx=shx_file, dbf=dbf_file, encoding=encoding) as sf:
        for sr in sf.iterShapeRecords(): 
            if city == "sendai" or city == "mitaka":
                id = sr.record["gml_id"]
            else:
                id = sr.record["id"]
            cls = sr.record["class"]

            if str(cls) not in ['1000', '1020', '2000', '3000']:
                continue

            if sr.shape.shapeType == 0:
                continue  # NULL シェイプの場合は次のループへ
            geom = Shape(sr.shape.__geo_interface__)
            #geom = truncate_coordinates(geom)
            
            if not geom.is_valid:
                print("Geometry could not be fixed. Skipping.")
                print(sr.record)
                continue

            data.append({
                "id" : id,
                "class": str(cls),
                "poly": geom
                })

    shp_file.close()
    shx_file.close()
    dbf_file.close()

    return data

def get_skeleton(poly):
    skeleton = polyskel.skeletonize(poly, holes=[])
    return skeleton

def calc_diff(poly_pred, poly_true):
    """
    判定ポリゴン毎に差分ポリゴンを作成し、差分距離(m)を算出する
    """
    polygons = []
    # Skeletonテスト
    poly_ = poly_pred.symmetric_difference(poly_true)
    if poly_.area < 0.001:
        return 0
    
    # MultiPolygon の場合は個別に simplify
    if isinstance(poly_, MultiPolygon):
        poly_ = [p.simplify(TOLERANCE, preserve_topology=True) for p in poly_.geoms]
    elif isinstance(poly_, Polygon):
        poly_ = poly_.simplify(TOLERANCE, preserve_topology=True)
        
    if type(poly_) is MultiPolygon:
        for poly_item in poly_.geoms:
            polygons.append(list(poly_item.exterior.coords))
    elif type(poly_) is Polygon:
        polygons.append(list(poly_.exterior.coords))
    elif type(poly_) is GeometryCollection:
        for poly_item in poly_.geoms:
            if type(poly_item) is Polygon:
                polygons.append(list(poly_item.exterior.coords))
            elif type(poly_) is MultiPolygon:
                for poly_item in poly_.geoms:
                    polygons.append(list(poly_item.exterior.coords))

    if not polygons:
        # 差分なし(完全一致)
        return 0

    for poly in polygons:
        if len(poly) == 0:
            # 差分なし(完全一致)
            return 0
        
        skeleton = get_skeleton(poly) #polyskel.skeletonize(poly, holes=[])
        ls_height = []

        #print("skeleton_count:", len(skeleton)) # 内接円の数
        for arc in skeleton:
            #print("source:", arc.source) # 内接円の中心ポイント
            tmp_height = 0
            # 内接円毎の処理
            for i in range(len(poly)):
                j = i+1
                if i == len(poly)-1:
                    j = 0
                pt_i = poly[i]
                pt_j = poly[j]

                # 内接円の半径を計算(中心点と各辺から高さを計算)
                tmp_poly = Polygon([pt_i, pt_j, (arc.source.x, arc.source.y)])
                tmp_line = LineString([pt_i, pt_j])

                if tmp_poly.area != 0 and tmp_line.length != 0:
                    height = tmp_poly.area*2 / tmp_line.length
                    if tmp_height != 0 and  tmp_height < height*2:
                        continue
                    # 高さ(円の半径)x2のうち、一番短いものを登録
                    tmp_height =  height*2

            ls_height.append(tmp_height)

    del skeleton
    gc.collect()

    # 各内接円から計算した距離のうち最大値を差分距離とする
    return max(ls_height)

def judge_points_count(points_count):
    """
    ポリコン単位で工数削減率区分を判定
    """
    if points_count < 10:
        return('A')
    elif points_count < 20:
        return('B')
    else:
        return('C')

def judge_polygon(check_pred, check_true, cheak_id):
    """
    道路ID単位のポリゴン判定
    """

    print("予測ポリゴン数：{} 正解ポリゴン数：{} id:{}:".format(len(check_pred), len(check_true), cheak_id))
    if len(check_pred)== 0:
        road_rank = 'C'
        polys_rank = ['C' for _ in check_true]
        return road_rank, polys_rank

    if len(check_true)== 0:
        road_rank = 'C'
        polys_rank = ['C' for _ in check_pred]
        return road_rank, polys_rank

    error_count = 0  # 誤りポリゴン数
    polys_rank = []
    for pred in check_pred:
        # 予測ポリゴン毎に処理
        set_area = []
        for test in check_true:
            # 予測と正解ポリゴンの建物IDが一致している場合の重なり面積を計算
            if pred.get('class') == test.get('class'):
                set_area.append(pred.get('poly').intersection(test.get('poly')).area)
            else:
                set_area.append(0)

        if max(set_area) == 0:
            # 重り面積が0の場合は誤りポリゴンとする
            error_count += 1
            polys_rank.append(judge_points_count(len(pred.get('poly').exterior.coords)))
            continue

        # 最も重なっているポリゴン同士の差分距離を計算
        diff = calc_diff(pred.get('poly'), check_true[set_area.index(max(set_area))].get('poly'))
        #print("skeleton_diff:", diff)

        if DIFF_DIST_REFERENCE < diff:
            # 予測と正解のポリゴンが基準値以上離れている場合を誤りとする
            error_count += 1
            polys_rank.append(judge_points_count(len(pred.get('poly').exterior.coords)))
        else:
            polys_rank.append('-')

    # 評価値　＝　誤りポリゴン数 / 道路IDの全ポリゴン数
    if error_count:
        if EVALUATION_REFERENCE < (error_count /len(check_pred)):
            # 評価値(誤り割合)が基準値以上
            road_rank = 'C'
        else:
            # 評価値(誤り割合)が基準値以下
            road_rank = 'B'
    else:
        # 修正不要（誤り箇所なし）
        road_rank = 'A'

    return road_rank, polys_rank

def write_file(shp_path, poly_judge_results):

    shx_path = shp_path[:-4] + ".shx"
    dbf_path = shp_path[:-4] + ".dbf"

    shp_file = open(shp_path.encode("utf-8"), "wb")
    shx_file = open(shx_path.encode("utf-8"), "wb")
    dbf_file = open(dbf_path.encode("utf-8"), "wb")

    with shapefile.Writer(
        shp=shp_file, shx=shx_file, dbf=dbf_file,
        encoding='Shift-JIS', shapeType=shapefile.POLYGON) as file:

        # 属性情報の設定
        file.field(name='road_id', fieldType='C')    # テキスト型のroad_id属性
        file.field(name='road_rank', fieldType='C')  # テキスト型のroad_rank属性
        file.field(name='poly_id', fieldType='C')    # テキスト型のpoly_id属性
        file.field(name='poly_rank', fieldType='C')  # テキスト型のpoly_rank属性

        # レコードとポリゴン情報の追加
        for i, poly in enumerate(poly_judge_results['poly']):
            file.record(poly_judge_results['road_id'][i], poly_judge_results['road_rank'][i],
                       poly_judge_results['poly_id'][i], poly_judge_results['poly_rank'][i])
            points = list(poly.exterior.coords)
            file.poly([points])

    shp_file.close()
    shx_file.close()
    dbf_file.close()

def main(shp_dir_pred, shp_dir_true, result_dir, city):
    """
    定性評価＆経済効果算出為のポリコン評価
    Arguments:
        shp_dir_pred: 予測結果shp格納フォルダ
        shp_dir_true: 正解shp格納フォルダ ★shpファイル名前は予測結果と同じことを前提
        result_dir: 評価結果フォルダ
    """
    pred_poly_count = 0
    true_poly_count = 0

    if os.path.exists(result_dir):
        shutil.rmtree(result_dir)
    os.makedirs(result_dir)
    
    all_road_judge_results = { 'file':[], 'road_id':[], 'road_rank':[] }
    all_poly_judge_results = { 'file':[], 'road_id':[], 'road_rank':[], 'poly_id':[], 'poly_rank':[] }

    shp_files_pred = [file for file in os.listdir(shp_dir_pred) if file[-4:]=='.shp']
    shp_files_true = [file for file in os.listdir(shp_dir_true) if file[-4:]=='.shp']
    
    #trueのポリゴン全て取り出しておく
    data_true = []
    for file in shp_files_true:
        shp_path_true = os.path.join(shp_dir_true, file)
        encoding = "Shift-JIS"
        if city=="gifu" or city=="kaga":
            encoding = "utf-8"
        data_true.extend(read_road_true(shp_path_true, encoding))


    for file in shp_files_pred:
        shp_path_pred = os.path.join(shp_dir_pred, file)
        
        # 予測データ：[{"id":string, "class":string, "poly":polygon}]
        data_pred = read_road_pred(shp_path_pred)   
        
        # 判定対象道路ID一覧
        ids = set([d['id'] for d in data_pred])

        # 道路ID単位で誤りポリコン数による道路ランク判定
        # 点数によるポリコンランク判定
        road_judge_results = { 'road_id':[], 'road_rank':[], 'polys_rank':[], 'polys':[] }
        if True:
            nr_processors = 8
            with Pool(nr_processors) as pool:
                results = []
                for check_id in ids:        
                    #if check_id != "tran_dda42548-18e6-4a39-b64c-e5e54d81bf09":
                    #    continue

                    #print("道路ID単位の処理:", check_id)
                    check_pred = [] # 予測ポリゴン：[{"id":string, "class":string, "poly":polygon}]
                    for data in data_pred:
                        if data.get('id') == check_id:
                            check_pred.append(data)
                            pred_poly_count += 1

                    check_true = [] # 正解ポリゴン：[{"id":string, "class":string, "poly":polygon}]
                    for data in data_true:
                        if data.get('id') == check_id:
                            check_true.append(data)
                            true_poly_count += 1

                    result = pool.apply_async(judge_polygon, args=(check_pred, check_true, check_id,))
                    results.append(result)

                    road_judge_results['road_id'].append(check_id)
                    road_judge_results['polys'].append([data['poly'] for data in check_pred])

                for result in results:
                    road_rank, polys_rank = result.get()
                    road_judge_results['road_rank'].append(road_rank)
                    road_judge_results['polys_rank'].append(polys_rank)
        else:
            results = []
            for check_id in ids:        
                #if check_id != "tran_4f29901e-588c-43ce-9fdd-e7f111d4f414":
                #    continue

                print("道路ID単位の処理:", check_id)

                check_pred = [] # 予測ポリゴン：[{"id":string, "class":string, "poly":polygon}]
                for data in data_pred:
                    if data.get('id') == check_id:
                        check_pred.append(data)

                check_true = [] # 正解ポリゴン：[{"id":string, "class":string, "poly":polygon}]
                for data in data_true:
                    if data.get('id') == check_id:
                        check_true.append(data)

                result = judge_polygon(check_pred, check_true, check_id)
                results.append(result)

                road_judge_results['road_id'].append(check_id)
                road_judge_results['polys'].append([data['poly'] for data in check_pred])

            for result in results:
                road_rank, polys_rank = result
                road_judge_results['road_rank'].append(road_rank)
                road_judge_results['polys_rank'].append(polys_rank)

        for i, road_id in enumerate(road_judge_results['road_id']):
            all_road_judge_results['file'].append(file)
            all_road_judge_results['road_id'].append(road_id)
            all_road_judge_results['road_rank'].append(road_judge_results['road_rank'][i])

        # 道路ランク判定結果のcsv出力
        print("道路ランク判定結果のcsv出力")
        df = pd.DataFrame({
            'road_id' : road_judge_results['road_id'],
            'road_rank' : road_judge_results['road_rank']  
            })
        df.to_csv(os.path.join(result_dir, file[:-4] + "_eval1.csv"), index=False)

        # ポリコンランク判定結果のcsv出力
        print("ポリゴンランク判定結果のcsv出力")
        poly_judge_results = { 'road_id':[], 'road_rank':[], 'poly_id':[], 'poly_rank':[], 'poly':[] }
        for i, road_id in enumerate(road_judge_results['road_id']):
            road_rank = road_judge_results['road_rank'][i]
            for j, poly in enumerate(road_judge_results['polys'][i]):
                poly_rank = road_judge_results['polys_rank'][i][j]

                poly_judge_results['road_id'].append(road_id)
                poly_judge_results['road_rank'].append(road_rank)
                poly_judge_results['poly_id'].append(str(j+1))
                poly_judge_results['poly_rank'].append(poly_rank)
                poly_judge_results['poly'].append(poly)

        for i, road_id in enumerate(poly_judge_results['road_id']):
            all_poly_judge_results['file'].append(file)
            all_poly_judge_results['road_id'].append(road_id)
            all_poly_judge_results['road_rank'].append(poly_judge_results['road_rank'][i])
            all_poly_judge_results['poly_id'].append(poly_judge_results['poly_id'][i])
            all_poly_judge_results['poly_rank'].append(poly_judge_results['poly_rank'][i])

        df = pd.DataFrame({
            'road_id' : poly_judge_results['road_id'],
            'road_rank' : poly_judge_results['road_rank'],
            'poly_id' : poly_judge_results['poly_id'],
            'poly_rank' : poly_judge_results['poly_rank']
            })
        df.to_csv(os.path.join(result_dir, file[:-4] + "_eval2.csv"), index=False)

        # shp出力
        print("shp出力")
        write_file(os.path.join(result_dir, file[:-4] + "_eval2.shp"), poly_judge_results)

    # 全道路ランク判定結果のcsv出力
    df = pd.DataFrame({
        'file' : all_road_judge_results['file'],
        'road_id' : all_road_judge_results['road_id'],
        'road_rank' : all_road_judge_results['road_rank']  
        })
    df.to_csv(os.path.join(result_dir, "all_eval1.csv"), index=False)
    
    # .txtファイルへの書き込み準備
    txt_file_path = os.path.join(result_dir, "result_rank.txt")  # 出力ファイル名
    with open(txt_file_path, "w") as f:  # "w" は書き込みモード

        print(f"道路ランクのカウント")
        f.write("道路ランクのカウント\n")  # ファイルにも書き込み

        rank_counts = df['road_rank'].value_counts(sort=False).sort_index()
        print(rank_counts)
        f.write(f"{rank_counts}\n")  # ファイルにも書き込み

        # 全ポリコンランク判定結果のcsv出力
        df = pd.DataFrame({
            'file': all_poly_judge_results['file'],
            'road_id': all_poly_judge_results['road_id'],
            'road_rank': all_poly_judge_results['road_rank'],
            'poly_id': all_poly_judge_results['poly_id'],
            'poly_rank': all_poly_judge_results['poly_rank']
        })
        df.to_csv(os.path.join(result_dir, "all_eval2.csv"), index=False)

        print(f"ポリゴンランクのカウント")
        f.write("ポリゴンランクのカウント\n")  # ファイルにも書き込み

        poly_rank_counts = df['poly_rank'].value_counts(sort=False).sort_index()
        print(poly_rank_counts)
        f.write(f"{poly_rank_counts}\n")  # ファイルにも書き込み

        print(f"予測ポリゴン数：{pred_poly_count}, 正解ポリゴン数：{true_poly_count}")
        f.write(f"予測ポリゴン数：{pred_poly_count}, 正解ポリゴン数：{true_poly_count}\n")

    print(f"結果は {txt_file_path} に保存されました。")

if __name__ == '__main__':

    #city = "hiroshima"
    #pred_name = "AAS2023ckpt_vectorized"
    #true_name = "true_v2.4"
    
    #city = "gifu"
    #pred_name = "pred_aas2023ckpt"
    #true_name = "true"

    #city = "sendai"
    #pred_name = "pred_5city"
    #true_name = "sendai_shp_lod2_add_id_intersection"
    
    #city = "mitaka"
    #pred_name = "pred_5city"
    #true_name = "mitaka_shp_lod2_add_id_intersection"
    
    city = "kaga"
    pred_name = "pred_512_8cm_5city"
    true_name = "kaga_shp_lod2_add_intersection"

    shp_dir_pred = os.path.join(city, pred_name)
    shp_dir_true = os.path.join(city, true_name)
    result_dir = os.path.join(city, "qual_eval_result", pred_name)
    
    main(shp_dir_pred, shp_dir_true, result_dir, city)
    print("Done")