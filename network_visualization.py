from flask import Flask, request, jsonify
from flask_cors import CORS
import pymysql
import json
import os

app = Flask(__name__)
CORS(app, resources={"/*": {"origins": "*"}}, methods=["GET", "POST", "OPTIONS"])

# 从环境变量获取数据库配置
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '123456')
DB_NAME = os.getenv('DB_NAME', 'patent_analysis_platform')

# 数据库连接配置
db_config = {
    'host': DB_HOST,
    'port': DB_PORT,
    'user': DB_USER,
    'password': DB_PASSWORD,
    'database': DB_NAME,
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

def get_conn():
    """获取数据库连接"""
    return pymysql.connect(**db_config)

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "code": 200,
        "message": "Network visualization service is running"
    })

@app.route("/api/network/get_data", methods=["POST", "OPTIONS"])
def get_network_data():
    """获取网络数据"""
    # 处理OPTIONS预检请求
    if request.method == "OPTIONS":
        return jsonify({"code": 200}), 200

    try:
        # 1. 校验请求格式
        if not request.is_json:
            return jsonify({"code": 400, "msg": "请求体必须为JSON格式"}), 400

        data = request.json
        domain_id = data.get("domain_id")  # 领域ID，为0表示全领域

        # 2. 获取网络数据
        nodes, links = get_network_nodes_links(domain_id)

        # 3. 返回结果
        return jsonify({
            "code": 200,
            "data": {
                "nodes": nodes,
                "links": links
            }
        })

    except Exception as e:
        print(f"获取网络数据错误: {str(e)}")
        return jsonify({"code": 500, "msg": f"服务器内部错误: {str(e)}"}), 500

def get_network_nodes_links(domain_id):
    """获取网络节点和边"""
    conn = get_conn()
    cursor = conn.cursor()

    try:
        # 1. 构建查询条件
        if domain_id and domain_id != 0:
            # 单领域查询
            patent_query = """
                SELECT 公开公告号 as publication_number, 引证 as citations, 
                       发明名称, 公开公告日, 申请专利权人, 发明人, IPC分类号, technology_domain_id
                FROM patents
                WHERE technology_domain_id = %s
            """
            cursor.execute(patent_query, (domain_id,))
        else:
            # 全领域查询
            patent_query = """
                SELECT 公开公告号 as publication_number, 引证 as citations, 
                       发明名称, 公开公告日, 申请专利权人, 发明人, IPC分类号, technology_domain_id
                FROM patents
            """
            cursor.execute(patent_query)

        patents = cursor.fetchall()

        # 2. 构建节点和边
        nodes = []
        links = []

        # 收集所有节点（包括被引用的专利）
        all_nodes = set()
        
        # 处理每个专利
        patent_info_map = {}
        for patent in patents:
            source = patent['publication_number']
            citations = patent['citations']
            
            # 保存专利详细信息
            patent_info_map[source] = {
                "title": patent.get('发明名称', ''),
                "pubDate": patent.get('公开公告日', ''),
                "applicant": patent.get('申请专利权人', ''),
                "inventor": patent.get('发明人', ''),
                "ipc": patent.get('IPC分类号', ''),
                "domainId": patent.get('technology_domain_id', 0)
            }
            # 打印调试信息
            print(f"专利号: {source}, technology_domain_id: {patent.get('technology_domain_id', 0)}")
            
            # 添加引用节点
            all_nodes.add(source)
            
            # 解析引证字段，提取被引专利号
            if citations:
                # 分割引证字段，支持多种分隔符
                separators = ['、', '，', ';', ',', '|', '\t', '\n', '\r']
                citation_text = str(citations)
                for sep in separators:
                    citation_text = citation_text.replace(sep, ' ')
                
                # 按空格分割，过滤空值
                citation_parts = [cp.strip() for cp in citation_text.split(' ') if cp.strip()]
                
                # 过滤出专利号（通常包含字母和数字，如CN1000000A、US1000000B1等）
                cited_patents = []
                for part in citation_parts:
                    # 简单判断：如果包含字母和数字，且长度合理（通常8-20个字符），则认为是专利号
                    if any(c.isalpha() for c in part) and any(c.isdigit() for c in part) and 8 <= len(part) <= 20:
                        cited_patents.append(part)
                
                # 添加被引节点和边
                for cited_patent in cited_patents:
                    if cited_patent:
                        all_nodes.add(cited_patent)
                        links.append({
                            "source": cited_patent,  # 被引用节点
                            "target": source,  # 引用节点
                            "type": "directed"
                        })

        # 添加节点
        for node_id in all_nodes:
            node_data = {
                "id": node_id,
                "label": node_id,
                "size": 15
            }
            # 为引用节点添加详细信息
            if node_id in patent_info_map:
                node_data["patentInfo"] = patent_info_map[node_id]
            nodes.append(node_data)

        return nodes, links

    finally:
        cursor.close()
        conn.close()

@app.route("/api/network/get_domains", methods=["GET"])
def get_domains():
    """获取所有技术领域"""
    conn = get_conn()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id, domain_name FROM technology_domains")
        domains = cursor.fetchall()

        # 添加全领域选项
        all_domain = [{"id": 0, "domain_name": "全领域"}]
        all_domain.extend(domains)

        return jsonify({
            "code": 200,
            "data": all_domain
        })

    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    app.run(host='127.0.0.1', port=5006, debug=False, threaded=True)
