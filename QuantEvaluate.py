# -*- coding: utf-8 -*-
import sys
import os
import numpy as np
import shapefile
from shapely.geometry import shape as Shape
import geopandas as gpd
#import polyskel
#from PIL import Image, ImageDraw
#import cv2
#import matplotlib.pyplot as plt
#import shapefile
#import math
#import yaml
#import datetime
#from shapely.geometry import shape as Shape
#from shapely.geometry import MultiPolygon
#from shapely import Polygon
#from shapely import LineString
#from shapely.validation import make_valid


np.set_printoptions(precision=4, floatmode='fixed', suppress=True)

def calculate_confusision_matrix(data_pred, data_true):
    conf_mx = []
    for pred_cls in ['1000', '1020', '2000', '3000']:
        conf_mx_ = []
        for true_cls in ['1000', '1020', '2000', '3000']:
            polys_pred = [elem['poly'] for elem in data_pred if elem['class']==pred_cls]
            polys_true = [elem['poly'] for elem in data_true if elem['class']==true_cls]
            overlap = 0.0
            for poly_pred in polys_pred:
                for poly_true in polys_true:
                    try:
                        if poly_pred.intersects(poly_true):
                            overlap += poly_pred.intersection(poly_true).area
                    except Exception as e:
                        print(e)
            conf_mx_.append(overlap)
        conf_mx.append(conf_mx_)
    return conf_mx


def IoU_from_confusions(confusions):
    """
    Computes IoU from confusion matrices.
    :param confusions: ([n_c, n_c], np.float32). n_c = number of classes.
                     GT
                -----------
                | TP | FP |
           PRED -----------
                | FN | TN |
                -----------
    :return: ([n_c] np.float32) IoU score
    """

    TP = np.diagonal(confusions)
    TP_plus_FN = np.sum(confusions, axis=0)
    TP_plus_FP = np.sum(confusions, axis=1)

    IoU = TP / (TP_plus_FP + TP_plus_FN - TP + 1e-6)
    return IoU


def FScore_from_confusions(confusions):
    """
    Computes FScore from confusion matrices.
    :param confusions: ([n_c, n_c], np.float32). n_c = number of classes.
                     GT
                -----------
                | TP | FP |
           PRED -----------
                | FN | TN |
                -----------
    :return: ([n_c] np.float32) F1-score, precision, recall
    """

    TP = np.diagonal(confusions)
    TP_plus_FN = np.sum(confusions, axis=0)
    TP_plus_FP = np.sum(confusions, axis=1)

    precision = TP / (TP_plus_FP + 1e-6)
    recall = TP / (TP_plus_FN + 1e-6)
    F1 = TP * 2 / (TP_plus_FP + TP_plus_FN + 1e-6)
    return F1, precision, recall


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

            data.append({
                "id" : id,
                "class": str(convert_class(cls, intersec)),
                "poly": geom
                })

    shp_file.close()
    shx_file.close()
    dbf_file.close()

    return data

def read_road_true(shp_path, city, encoding="Shift-JIS"):
    """
    正解シェープファイル読み込み機能
    """
    shx_path = shp_path[:-4] + ".shx"
    dbf_path = shp_path[:-4] + ".dbf"

    shp_file = open(shp_path.encode("utf-8"), "rb")
    shx_file = open(shx_path.encode("utf-8"), "rb")
    dbf_file = open(dbf_path.encode("utf-8"), "rb")
    #print("shp_path:",shp_path)
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

            if sr.shape is None or sr.shape.shapeType == 0:  # shapeType 0 は NULL
                print("NULL shape found:", sr.shape)
                continue
            geom = Shape(sr.shape.__geo_interface__)

            data.append({
                "id" : id,
                "class": str(cls),
                "poly": geom
                })

    shp_file.close()
    shx_file.close()
    dbf_file.close()

    return data

def read_road_true_gpd(shp_path, city, epsg=None, encoding="Shift-JIS"):
    """
    正解シェープファイル読み込み機能（GeoPandas版）
    
    Parameters:
        shp_path (str): シェープファイルのパス
        city (str): 都市名
        epsg (int or None): 変換先のEPSGコード（例: '3857'）。Noneの場合は変換しない
        encoding (str): ファイルのエンコーディング（デフォルト: "Shift-JIS"）
    
    Returns:
        list[dict]: シェープファイルのデータを格納したリスト
    """
    # シェープファイルをGeoPandasで読み込む
    gdf = gpd.read_file(shp_path, encoding=encoding)
    
    # EPSGコードが指定されていれば座標系を変換
    if epsg:
        gdf = gdf.to_crs(epsg = epsg)
    
    data = []
    
    # 必要なフィールドを抽出
    for _, row in gdf.iterrows():
        # id フィールドの取得
        if city in ["sendai", "mitaka"]:
            id = row.get("gml_id")
        else:
            id = row.get("id")
        
        # class フィールドの取得とフィルタリング
        cls = row.get("class")
        if str(cls) not in ['1000', '1020', '2000', '3000']:
            continue
        
        # geometry の取得と Shapely 形式への変換
        geom = row.geometry
        if geom is None or geom.is_empty:
            print("NULL geometry found:", row.geometry)
            continue
        
        # 必要な情報をリストに追加
        data.append({
            "id": id,
            "class": str(cls),
            "poly": Shape(geom)  # Shapely 形式に変換
        })
    
    return data

def main(shp_dir_pred, shp_dir_true, city, epsg = None):
    shp_path_pred = [os.path.join(shp_dir_pred, file) for file in os.listdir(shp_dir_pred) if file[-4:]=='.shp']
    shp_path_true = [os.path.join(shp_dir_true, file) for file in os.listdir(shp_dir_true) if file[-4:]=='.shp']

    # 予測データ：[{"id":string, "class":string, "poly":polygon}]
    data_pred = []
    for shp_path in shp_path_pred:
        data_pred += read_road_pred(shp_path)     
        
    # 正解データ：[{"id":string, "class":string, "poly":polygon}]
    data_true = []
    encoding = "CP932"#"Shift-JIS"
    if city=="gifu" or city=="kaga":
        encoding = "utf-8"
    if epsg is not None:
        for shp_path in shp_path_true:
            data_true += read_road_true_gpd(shp_path, city, epsg, encoding)
    else:
        for shp_path in shp_path_true:
            data_true += read_road_true(shp_path, city, encoding)

    # 判定対象建物ID一覧
    ids = list(dict.fromkeys([d.get('id') for d in data_pred]))

    # confusion matrix算出
    result = {}
    for check_id in ids:
        # 建物ID単位の処理
        #print(check_id)
        check_pred = []
        check_true = []

        for data in data_pred:
            if data.get('id') == check_id:
                check_pred.append(data)

        for data in data_true:
            if data.get('id') == check_id:
                check_true.append(data)

        conf_mx = calculate_confusision_matrix(check_pred, check_true)
        result[check_id] = conf_mx

    # F値計算
    conf_mx = np.zeros((4,4), np.float64)
    for key, value in result.items():
        conf_mx += np.array(value)
    print("Confusion Matrix:\n", conf_mx)

    # IOU計算
    IoU = IoU_from_confusions(conf_mx)
    print("IoU:\n", IoU)

    # 出力
    F1, precision, recall = FScore_from_confusions(conf_mx)
    print("F1:\n", F1)
    print("precision:\n", precision)
    print("recall:\n", recall)


if __name__ == '__main__':

    epsg=None

    shp_dir_pred = "./hiroshima/AAS2023ckpt_vectorized"
    shp_dir_true = "./hiroshima/true_v2.4" 
    city = "hiroshima"

    #shp_dir_pred = "./gifu/pred_8cm_4city"
    #shp_dir_true = "./gifu/true" 
    #city = "gifu"

    #shp_dir_pred = "./sendai/pred_8cm_4city"
    #shp_dir_true = "./sendai/sendai_shp_lod2_add_id_intersection" 
    #city = "sendai"
    #epsg = 6678

    #shp_dir_pred = "./mitaka/pred_4city"
    #shp_dir_true = "./mitaka/mitaka_shp_lod2_add_id_intersection" 
    #city = "mitaka"
    #epsg = 6677

    #shp_dir_pred = "./kaga/pred_4city"
    #shp_dir_true = "./kaga/kaga_shp_lod2_add_intersection" 
    #city = "kaga"
    
        
    main(shp_dir_pred, shp_dir_true, city, epsg)
    print(f"{city} Done")