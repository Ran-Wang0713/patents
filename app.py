from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, text
import pandas as pd
from datetime import datetime
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, methods=["GET", "POST", "OPTIONS"])

# 从环境变量获取数据库配置
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '123456')
DB_NAME = os.getenv('DB_NAME', 'patent_analysis_platform')

# 数据库连接（统一SQLAlchemy，全局唯一）
db_url = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
db_engine = create_engine(db_url)

# 首页测试
@app.route('/')
def hello():
    return "智能专利分析平台API已启动！"

# ================================
# 原有专利相关API（完全保留，无修改）
# ================================

# API 1: 获取专利列表
@app.route('/api/patents', methods=['GET'])
def get_patents():
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    keyword = request.args.get('keyword', '')
    applicant = request.args.get('applicant', '')
    domain = request.args.get('domain', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    patent_type = request.args.get('patent_type', '')

    offset = (page - 1) * size

    sql = """
        SELECT DISTINCT p.id, p.公开公告号 as publication_number, p.publication_date, 
               p.发明名称 as title, p.patent_type, p.legal_status, td.domain_name as technology_domain
        FROM patents p
        LEFT JOIN technology_domains td ON p.technology_domain_id = td.id
        LEFT JOIN patent_applicant pa ON p.id = pa.patent_id
        LEFT JOIN applicants a ON pa.applicant_id = a.id
        WHERE 1=1
    """
    params = {}

    if keyword:
        sql += " AND (p.发明名称 LIKE :keyword OR p.摘要 LIKE :keyword)"
        params['keyword'] = f'%{keyword}%'

    if applicant:
        sql += " AND p.申请专利权人 LIKE CONCAT('%', :applicant, '%')"
        params['applicant'] = applicant

    if domain:
        sql += " AND td.domain_name = :domain"
        params['domain'] = domain

    if start_date:
        sql += " AND p.publication_date >= :start_date"
        params['start_date'] = start_date

    if end_date:
        sql += " AND p.publication_date <= :end_date"
        params['end_date'] = end_date

    if patent_type:
        sql += " AND p.patent_type = :patent_type"
        params['patent_type'] = patent_type

    sql += " ORDER BY p.publication_date DESC LIMIT :size OFFSET :offset"
    params['size'] = size
    params['offset'] = offset

    count_sql = "SELECT COUNT(DISTINCT p.id) as total FROM " + sql.split('FROM')[1].split('ORDER BY')[0]
    count_params = {k: v for k, v in params.items() if k not in ['size', 'offset']}

    with db_engine.connect() as conn:
        total_result = conn.execute(text(count_sql), count_params).fetchone()
        total = total_result[0] if total_result else 0
        result = conn.execute(text(sql), params)
        patents = [dict(row) for row in result.mappings()]

    return jsonify({
        'patents': patents,
        'pagination': {
            'page': page,
            'size': size,
            'total': total,
            'pages': (total + size - 1) // size
        }
    })

# API 2: 获取专利详情
@app.route('/api/patent/<pub_number>')
def get_patent_detail(pub_number):
    sql = """
        SELECT 
            p.id,
            p.公开公告号 as publication_number,
            p.publication_date,
            p.发明名称 as title,
            p.摘要 as abstract,
            p.引证 as citations,
            p.patent_type,
            p.legal_status,
            td.domain_name,
            p.申请专利权人 as original_applicants,
            p.发明人 as original_inventors,
            p.IPC分类号 as original_ipc,
            GROUP_CONCAT(DISTINCT a.name SEPARATOR '; ') as normalized_applicants,
            GROUP_CONCAT(DISTINCT i.name SEPARATOR '; ') as normalized_inventors,
            GROUP_CONCAT(DISTINCT ipc.ipc_code SEPARATOR '; ') as normalized_ipc
        FROM patents p
        LEFT JOIN technology_domains td ON p.technology_domain_id = td.id
        LEFT JOIN patent_applicant pa ON p.id = pa.patent_id
        LEFT JOIN applicants a ON pa.applicant_id = a.id
        LEFT JOIN patent_inventor pi ON p.id = pi.patent_id
        LEFT JOIN inventors i ON pi.inventor_id = i.id
        LEFT JOIN patent_ipc pipc ON p.id = pipc.patent_id
        LEFT JOIN ipc_classes ipc ON pipc.ipc_class_id = ipc.id
        WHERE p.公开公告号 LIKE CONCAT('%', :pub_num, '%')
        GROUP BY p.id
    """

    with db_engine.connect() as conn:
        patent = conn.execute(text(sql), {'pub_num': pub_number}).mappings().fetchone()
        if not patent:
            return jsonify({'error': '专利不存在'}), 404

        citation_sql = """
            SELECT p2.公开公告号 as publication_number, p2.发明名称 as title 
            FROM patent_citations pc
            JOIN patents p1 ON pc.citing_patent_id = p1.id
            JOIN patents p2 ON pc.cited_patent_id = p2.id
            WHERE p1.公开公告号 LIKE CONCAT('%', :pub_num, '%')
        """
        citations = [dict(row) for row in conn.execute(text(citation_sql), {'pub_num': pub_number}).mappings()]

        patent_dict = dict(patent)
        patent_dict['citations_detail'] = citations

    return jsonify(patent_dict)

# API 3: 技术领域统计
@app.route('/api/domain-statistics')
def get_domain_statistics():
    sql = """
        SELECT td.domain_name, COUNT(p.id) as patent_count,
               COUNT(DISTINCT a.id) as applicant_count,
               MIN(p.publication_date) as start_date,
               MAX(p.publication_date) as end_date
        FROM technology_domains td
        LEFT JOIN patents p ON td.id = p.technology_domain_id
        LEFT JOIN patent_applicant pa ON p.id = pa.patent_id
        LEFT JOIN applicants a ON pa.applicant_id = a.id
        GROUP BY td.id, td.domain_name
        ORDER BY patent_count DESC
    """

    with db_engine.connect() as conn:
        result = conn.execute(text(sql))
        statistics = [dict(row) for row in result.mappings()]

    return jsonify(statistics)

# API 4: 时间趋势分析
@app.route('/api/trend-analysis')
def get_trend_analysis():
    years = int(request.args.get('years', 10))
    domain = request.args.get('domain', '')

    end_year = datetime.now().year
    start_year = end_year - years + 1

    sql = """
        SELECT 
            YEAR(publication_date) as year, 
            patent_type,
            COUNT(*) as count
        FROM patents
        WHERE publication_date IS NOT NULL
          AND YEAR(publication_date) BETWEEN :start_year AND :end_year
    """
    params = {'start_year': start_year, 'end_year': end_year}

    if domain:
        sql += " AND technology_domain_id = (SELECT id FROM technology_domains WHERE domain_name = :domain)"
        params['domain'] = domain

    sql += " GROUP BY YEAR(publication_date), patent_type ORDER BY year, patent_type"

    with db_engine.connect() as conn:
        result = conn.execute(text(sql), params)
        data = [dict(row) for row in result.mappings()]

    all_years = list(range(start_year, end_year + 1))
    patent_types = ['发明', '实用新型', '外观设计']
    trend_data = []
    for year in all_years:
        year_data = {'year': year}
        for p_type in patent_types:
            year_data[p_type] = 0
        trend_data.append(year_data)

    for item in data:
        year = item['year']
        p_type = item['patent_type']
        count = item['count']
        year_entry = next((entry for entry in trend_data if entry['year'] == year), None)
        if year_entry and p_type in year_entry:
            year_entry[p_type] = count

    return jsonify(trend_data)

# API 5: 申请人排名
@app.route('/api/applicant-ranking')
def get_applicant_ranking():
    limit = int(request.args.get('limit', 10))
    domain = request.args.get('domain', '')

    sql = """
        SELECT a.name, a.applicant_type, 
               COUNT(DISTINCT pa.patent_id) as patent_count,
               MIN(p.publication_date) as first_patent,
               MAX(p.publication_date) as latest_patent
        FROM applicants a
        JOIN patent_applicant pa ON a.id = pa.applicant_id
        JOIN patents p ON pa.patent_id = p.id
    """
    params = {}

    if domain:
        sql += " JOIN technology_domains td ON p.technology_domain_id = td.id WHERE td.domain_name = :domain"
        params['domain'] = domain

    sql += " GROUP BY a.id, a.name, a.applicant_type ORDER BY patent_count DESC LIMIT :limit"
    params['limit'] = limit

    with db_engine.connect() as conn:
        result = conn.execute(text(sql), params)
        ranking = [dict(row) for row in result.mappings()]

    return jsonify(ranking)

# API 6: IPC分类分析
@app.route('/api/ipc-analysis')
def get_ipc_analysis():
    sql = """
        SELECT 
            ipc.ipc_code,
            ipc.ipc_section, 
            ipc.ipc_class, 
            COUNT(DISTINCT pipc.patent_id) as patent_count
        FROM ipc_classes ipc
        JOIN patent_ipc pipc ON ipc.id = pipc.ipc_class_id
        GROUP BY ipc.id, ipc.ipc_code, ipc.ipc_section, ipc.ipc_class
        ORDER BY patent_count DESC
        LIMIT 20
    """

    with db_engine.connect() as conn:
        result = conn.execute(text(sql))
        analysis = [dict(row) for row in result.mappings()]

    return jsonify(analysis)

# API 7: 相似专利推荐
@app.route('/api/similar-patents/<pub_number>')
def get_similar_patents(pub_number):
    limit = int(request.args.get('limit', 5))

    sql = """
        SELECT p2.公开公告号 as publication_number, p2.发明名称 as title, p2.publication_date,
               COUNT(DISTINCT pipc2.ipc_class_id) as common_ipc_count
        FROM patents p1
        JOIN patent_ipc pipc1 ON p1.id = pipc1.patent_id
        JOIN patent_ipc pipc2 ON pipc1.ipc_class_id = pipc2.ipc_class_id
        JOIN patents p2 ON pipc2.patent_id = p2.id
        WHERE p1.公开公告号 LIKE CONCAT('%', :pub_num, '%') 
          AND p2.公开公告号 NOT LIKE CONCAT('%', :pub_num, '%')
        GROUP BY p2.id
        ORDER BY common_ipc_count DESC, p2.publication_date DESC
        LIMIT :limit
    """

    with db_engine.connect() as conn:
        result = conn.execute(text(sql), {'pub_num': pub_number, 'limit': limit})
        similar_patents = [dict(row) for row in result.mappings()]

    return jsonify(similar_patents)

# API 8: 按技术领域获取专利
@app.route('/api/patents/by-domain/<domain_name>')
def get_patents_by_domain(domain_name):
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 20))
    offset = (page - 1) * size

    sql = """
        SELECT p.公开公告号 as publication_number, p.发明名称 as title, 
               p.publication_date, p.申请专利权人 as applicants
        FROM patents p
        JOIN technology_domains td ON p.technology_domain_id = td.id
        WHERE td.domain_name = :domain_name
        ORDER BY p.publication_date DESC
        LIMIT :size OFFSET :offset
    """

    with db_engine.connect() as conn:
        result = conn.execute(text(sql), {
            'domain_name': domain_name,
            'size': size,
            'offset': offset
        })
        patents = [dict(row) for row in result.mappings()]

        count_sql = "SELECT COUNT(*) as total FROM patents p JOIN technology_domains td ON p.technology_domain_id = td.id WHERE td.domain_name = :domain_name"
        total = conn.execute(text(count_sql), {'domain_name': domain_name}).scalar()

    return jsonify({
        'patents': patents,
        'pagination': {
            'page': page,
            'size': size,
            'total': total,
            'pages': (total + size - 1) // size
        }
    })

# ================================
# ✅ 导入历史接口（彻底修复：路由正确、连接统一、无拼写错误）
# ================================
@app.route("/api/import/history", methods=["GET"])
def get_import_history():
    try:
        with db_engine.connect() as conn:
            # 按时间倒序，最新的在最前面
            result = conn.execute(text("SELECT * FROM import_history ORDER BY create_time DESC"))
            data = []
            for row in result.mappings():
                item = dict(row)
                # 格式化时间，适配前端显示
                if 'create_time' in item and item['create_time']:
                    item['create_time'] = item['create_time'].strftime("%Y-%m-%d %H:%M")
                # 统一字段名，完全匹配前端表格
                item['fileName'] = item['file_name']
                item['count'] = item['count']
                item['type'] = item['type']
                item['id'] = item['id']
                data.append(item)
            
            print(f"✅ 查询到 {len(data)} 条导入历史")
            return jsonify({
                "code": 200,
                "msg": "查询成功",
                "data": data
            })
    except Exception as e:
        print(f"❌ 获取历史失败: {str(e)}")
        return jsonify({"code": 500, "msg": str(e), "data": []})

# ================================
# ✅ 删除接口（彻底修复：路由正确、连接统一、联动删除数据库）
# ================================
@app.route("/api/import/delete/<int:history_id>", methods=["DELETE"])
def delete_import_history(history_id):
    try:
        with db_engine.connect() as conn:
            # 1. 查询要删除的历史记录，获取文件名
            history = conn.execute(text("SELECT file_name FROM import_history WHERE id = :id"), {"id": history_id}).fetchone()
            if not history:
                return jsonify({"code": 404, "msg": "记录不存在"}), 404

            file_name = history[0]

            # 2. 删除patents表中对应本次导入的所有专利
            conn.execute(text("DELETE FROM patents WHERE file_name = :file_name"), {"file_name": file_name})
            deleted_patents = conn.rowcount

            # 3. 删除导入历史记录
            conn.execute(text("DELETE FROM import_history WHERE id = :id"), {"id": history_id})
            conn.commit()

            print(f"✅ 删除成功：历史ID={history_id}，文件名={file_name}，删除专利{deleted_patents}条")
            return jsonify({
                "code": 200,
                "msg": f"删除成功，共删除{deleted_patents}条专利数据",
                "data": {"deleted_count": deleted_patents}
            })
    except Exception as e:
        print(f"❌ 删除失败: {str(e)}")
        return jsonify({"code": 500, "msg": str(e)})

# ================================
# 启动服务（端口5000，唯一入口）
# ================================
if __name__ == '__main__':
    app.run(debug=True, host="127.0.0.1", port=5000)