from flask import Flask, request, jsonify
from flask_cors import CORS
import pymysql
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
import jieba  # 新增：中文分词
from datetime import datetime
import warnings
import os

warnings.filterwarnings('ignore')

app = Flask(__name__)
# 完整跨域配置，彻底解决前端请求问题
CORS(app, resources={r"/*": {"origins": "*"}}, methods=["GET", "POST", "OPTIONS"])

# 从环境变量获取数据库配置
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '123456')
DB_NAME = os.getenv('DB_NAME', 'patent_analysis_platform')

# 数据库连接
def get_conn():
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10
        )
        return conn
    except Exception as e:
        print(f"数据库连接失败: {str(e)}")
        raise

# 数据预处理（兼容ID/名称双输入）
def preprocess_data(domain_input):
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()

        if str(domain_input).isdigit():
            domain_id = int(domain_input)
        else:
            # 适配你真实的数据库字段
            cursor.execute("SELECT id FROM technology_domains WHERE domain_name = %s", (domain_input,))
            domain_result = cursor.fetchone()
            if not domain_result:
                raise ValueError(f"未找到技术领域：{domain_input}")
            domain_id = domain_result['id']

        cursor.execute("""
            SELECT 公开公告日, 申请专利权人, IPC分类号, 摘要, 发明名称, 引证
            FROM patents
            WHERE technology_domain_id = %s AND 公开公告日 IS NOT NULL AND 公开公告日 != ''
        """, (domain_id,))

        patents = []
        for row in cursor.fetchall():
            patents.append({
                "publication_date": row['公开公告日'],
                "applicant": row['申请专利权人'] or "",
                "ipc": row['IPC分类号'] if row['IPC分类号'] else "",
                "abstract": row['摘要'] if row['摘要'] else "",
                "title": row['发明名称'] if row['发明名称'] else "",
                "citation": row['引证'] if row['引证'] else ""
            })

        year_data = {}
        for patent in patents:
            date_str = patent.get("publication_date", "")
            if not date_str:
                continue
            try:
                if isinstance(date_str, str):
                    date_str = date_str.replace('.', '-').replace('/', '-')
                    year = int(date_str[:4])
                else:
                    year = date_str.year if hasattr(date_str, 'year') else None

                if year and 1900 <= year <= datetime.now().year:
                    if year not in year_data:
                        year_data[year] = []
                    year_data[year].append(patent)
            except:
                continue

        sorted_years = sorted(year_data.keys())
        return year_data, sorted_years, patents

    finally:
        if conn:
            conn.close()

# ==============================
# ✅ 修复：中文关键词提取（用jieba分词，适配中文）
# ==============================
# 中文停用词表（可自行补充）
stop_words = set([
    '的', '了', '和', '是', '在', '我', '有', '也', '就', '都', '要', '这', '那', '个',
    '中', '上', '下', '来', '去', '说', '看', '使', '等', '可以', '用于', '包括', '其中',
    '一种', '所述', '其特征在于', '方法', '装置', '系统', '设备', '模块', '单元'
])

def extract_chinese_keywords(texts, top_n=50):
    valid_texts = [t.strip() for t in texts if t and t.strip()]
    if not valid_texts:
        return {}

    try:
        # 1. 对所有文本进行jieba分词
        segmented_texts = []
        for text in valid_texts:
            words = jieba.lcut(text)
            # 过滤停用词、单字、非中文
            filtered_words = [
                word for word in words
                if len(word) >= 2
                and word not in stop_words
                and '\u4e00' <= word <= '\u9fff'  # 仅保留中文字符
            ]
            segmented_texts.append(' '.join(filtered_words))

        # 2. TF-IDF提取关键词
        vectorizer = TfidfVectorizer(
            max_features=1000,
            ngram_range=(1, 1),  # 仅提取单个词
            min_df=2,
            max_df=0.8
        )
        tfidf = vectorizer.fit_transform(segmented_texts)
        scores = tfidf.sum(axis=0).A1
        words = vectorizer.get_feature_names_out()

        # 3. 按得分排序，取前top_n
        word_score = {}
        for word, score in zip(words, scores):
            word_score[word] = round(float(score), 4)

        sorted_words = sorted(word_score.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_words[:top_n])

    except Exception as e:
        print(f"关键词提取错误: {str(e)}")
        return {}

# ✅ 提取全局关键词（合并所有年份，不按年度拆分）
def extract_global_keywords(patents, top_n=50):
    all_text = []
    for p in patents:
        text = f"{p['title']} {p['abstract']}".strip()
        if text:
            all_text.append(text)
    return extract_chinese_keywords(all_text, top_n=top_n)

# 其他工具函数（保持不变）
def calculate_tech_heat_score(keyword_trends):
    if len(keyword_trends) < 2:
        return 50.0
    recent, prev = keyword_trends[-1], keyword_trends[-2]
    new_ratio = len(set(recent.keys()) - set(prev.keys())) / len(recent.keys()) if recent else 0
    change = 0
    for k in set(recent.keys()) & set(prev.keys()):
        change += np.clip((recent[k] - prev[k]) / (prev[k] or 0.0001), -1, 1)
    avg_change = change / len(set(recent.keys()) & set(prev.keys())) if set(recent.keys()) & set(prev.keys()) else 0
    return round(max(0, min(100, 50 + new_ratio*30 + avg_change*20)), 2)

def holt_smoothing(data, forecast_period=3):
    if not data:
        return [0]*forecast_period
    valid = [float(x) for x in data if x>0]
    if len(valid) < 2:
        return [round(valid[0],2)]*forecast_period if valid else [0]*forecast_period
    level, trend = np.zeros(len(valid)), np.zeros(len(valid))
    level[0], trend[0] = valid[0], (valid[1]-valid[0]) if valid[1]!=valid[0] else 0.01
    for t in range(1, len(valid)):
        level[t] = 0.3*valid[t] + 0.7*(level[t-1]+trend[t-1])
        trend[t] = 0.3*(level[t]-level[t-1]) + 0.7*trend[t-1]
    return [round(max(0, level[-1]+h*trend[-1]),2) for h in range(1, forecast_period+1)]

def calculate_quantity_score(hist, forecast):
    if len(hist) < 2:
        return 50.0
    hist_growth = np.clip((hist[-1]-hist[0])/hist[0], -1, 2)
    fore_growth = np.clip((forecast[-1]-hist[-1])/hist[-1], -1, 2) if hist[-1]>0 else 0
    return round(max(0, min(100, 50 + hist_growth*30 + fore_growth*20)), 2)

def calculate_innovation_score(applicant_count, citation_rate):
    return round(min(100, applicant_count*0.2 + citation_rate*0.1), 2)

def get_trend_level(score):
    if score >=90: return "高速增长"
    elif score >=80: return "稳步增长"
    elif score >=70: return "小幅增长"
    elif score >=60: return "平稳"
    elif score >=50: return "小幅波动"
    elif score >=40: return "小幅下滑"
    elif score >=30: return "明显下滑"
    else: return "严重下滑"

# 根路径测试
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "code":200,
        "message":"Trend prediction service is running"
    })

# ✅ 最终修复版预测接口
@app.route("/api/trend/predict", methods=["POST", "OPTIONS"])
def predict_trend():
    # 处理OPTIONS预检请求
    if request.method == "OPTIONS":
        return jsonify({"code":200}), 200

    try:
        # 1. 校验请求格式
        if not request.is_json:
            return jsonify({"code":400, "msg":"请求体必须为JSON格式"}),400

        data = request.json
        domain_input = data.get("domain_id")
        forecast_years = int(data.get("forecast_years", 1))

        # 2. 校验参数
        if not domain_input:
            return jsonify({"code":400, "msg":"缺少必要参数：domain_id"}),400
        if not 1<=forecast_years<=10:
            return jsonify({"code":400, "msg":"预测年份必须为1-10之间的整数"}),400

        # 3. 数据预处理
        year_data, sorted_years, patents = preprocess_data(domain_input)

        # 4. 无数据兜底
        if not patents:
            return jsonify({
                "code":200,
                "data":{
                    "trend_level":"无数据",
                    "final_score":35,
                    "future_forecasts":[0]*forecast_years,
                    "overall_keywords":{}
                }
            })

        # 5. 提取全局关键词（修复后，中文适配）
        overall_keywords = extract_global_keywords(patents, top_n=50)

        # 6. 提取年度关键词趋势
        keyword_trends = []
        for year in sorted_years:
            year_patents = year_data[year]
            year_texts = [f"{p['title']} {p['abstract']}".strip() for p in year_patents]
            year_keywords = extract_chinese_keywords(year_texts, top_n=20)
            keyword_trends.append(year_keywords)

        # 7. 计算各项得分
        historical_data = [len(year_data[y]) for y in sorted_years]
        future_forecasts = holt_smoothing(historical_data, forecast_years)
        quantity_score = calculate_quantity_score(historical_data, future_forecasts)

        applicant_count = len(set(p["applicant"] for p in patents if p["applicant"]))
        citation_rate = (sum(1 for p in patents if p["citation"]) / len(patents)) * 100
        innovation_score = calculate_innovation_score(applicant_count, citation_rate)

        tech_heat_score = calculate_tech_heat_score(keyword_trends)
        final_score = round(tech_heat_score*0.3 + quantity_score*0.4 + innovation_score*0.3, 2)
        trend_level = get_trend_level(final_score)

        # 7. 构建年度关键词趋势字典
        keyword_trends_dict = {}
        for i, year in enumerate(sorted_years):
            keyword_trends_dict[year] = keyword_trends[i]

        # 8. 返回结果
        return jsonify({
            "code":200,
            "data":{
                "tech_heat_score": tech_heat_score,
                "quantity_score": quantity_score,
                "innovation_score": innovation_score,
                "final_score": final_score,
                "trend_level": trend_level,
                "future_forecasts": future_forecasts,
                "historical_data": historical_data,
                "years": sorted_years,
                "keyword_trends": keyword_trends_dict,
                "overall_keywords": overall_keywords  # ✅ 全局关键词，中文适配
            }
        })

    except Exception as e:
        print(f"预测错误: {str(e)}")
        return jsonify({"code":500, "msg":f"服务器内部错误: {str(e)}"}),500

if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5005, debug=False, threaded=True)