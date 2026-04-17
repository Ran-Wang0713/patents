from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import pymysql
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, methods=["GET", "POST", "OPTIONS"])

# 从环境变量获取数据库配置
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', '3306'))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '123456')
DB_NAME = os.getenv('DB_NAME', 'patent_analysis_platform')

# 数据库配置
def get_conn():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4"
    )

# 初始化导入历史表
def init_import_history_table():
    try:
        conn = get_conn()
        cursor = conn.cursor()
        # 先创建表
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS import_history (
            id INT PRIMARY KEY AUTO_INCREMENT,
            file_name VARCHAR(255) NULL,
            count INT NOT NULL,
            type VARCHAR(20) NOT NULL,
            domain_id INT DEFAULT 5,
            create_time DATETIME DEFAULT NOW()
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        cursor.execute(create_table_sql)
        
        # 检查并添加domain_id列（如果不存在）
        cursor.execute("SHOW COLUMNS FROM import_history LIKE 'domain_id'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE import_history ADD COLUMN domain_id INT DEFAULT 5")
        
        conn.commit()
        print("import_history 表初始化成功")
    except Exception as e:
        print(f"表初始化提示: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# 导入接口（支持追加、去重、记录文件名、可删除）
@app.route("/api/import/excel", methods=["POST"])
def import_excel():
    try:
        file = request.files["file"]
        domain_id = request.form.get("domain_id", "5")  # 默认5G领域
        df = pd.read_excel(file)
        print(f"✅ 读取 {file.filename} 成功，共 {len(df)} 行数据，领域ID: {domain_id}")

        conn = get_conn()
        cursor = conn.cursor()
        total_insert = 0
        total_skip = 0

        for idx, row in df.iterrows():
            patent_no = str(row.get("公开（公告）号", "")).strip()
            patent_name = str(row.get("发明名称", "")).strip()

            if not patent_no or not patent_name:
                total_skip += 1
                continue

            # 查重：已存在则跳过
            cursor.execute("SELECT id FROM patents WHERE 公开公告号 = %s", (patent_no,))
            if cursor.fetchone():
                total_skip += 1
                continue

            # ✅ 插入专利（已包含 file_name）
            cursor.execute("""
                INSERT INTO patents (
                    公开公告号, 发明名称, 公开公告日, 申请专利权人, 发明人, 
                    摘要, IPC分类号, 引证, technology_domain_id, file_name
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                patent_no,
                patent_name,
                str(row.get("公开（公告）日", "")).strip(),
                str(row.get("申请（专利权）人", "")).strip(),
                str(row.get("发明人", "")).strip(),
                str(row.get("摘要", "")).strip(),
                str(row.get("IPC分类号", "")).strip(),
                str(row.get("引证", "")).strip(),
                domain_id,
                file.filename
            ))
            total_insert += 1

        # 记录导入历史
        cursor.execute("""
            INSERT INTO import_history (file_name, count, type, create_time, domain_id)
            VALUES (%s, %s, %s, NOW(), %s)
        """, (file.filename, total_insert, "excel", domain_id))

        conn.commit()
        return jsonify({
            "code": 200,
            "msg": f"导入成功：新增 {total_insert} 条，跳过 {total_skip} 条",
            "data": {"patent_count": total_insert}
        })

    except Exception as e:
        print(f"❌ 导入失败: {str(e)}")
        return jsonify({"code": 500, "msg": str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# 获取导入历史记录
@app.route("/api/import/history", methods=["GET"])
def get_import_history():
    try:
        conn = get_conn()
        cursor = conn.cursor()
        # 查询导入历史记录，按创建时间倒序排列
        cursor.execute("""
            SELECT 
                ih.id, 
                ih.file_name, 
                ih.count as data_count, 
                ih.type as import_type, 
                ih.domain_id, 
                td.domain_name,
                ih.create_time as import_time
            FROM import_history ih
            LEFT JOIN technology_domains td ON ih.domain_id = td.id
            ORDER BY ih.create_time DESC
        """)
        history = []
        for row in cursor.fetchall():
            history.append({
                "id": row[0],
                "file_name": row[1],
                "data_count": row[2],
                "import_type": row[3],
                "domain_id": row[4],
                "domain_name": row[5] or "5G",
                "import_time": row[6].strftime("%Y-%m-%d %H:%M:%S")
            })
        return jsonify({
            "code": 200,
            "data": history
        })
    except Exception as e:
        print(f"❌ 获取导入历史失败: {str(e)}")
        return jsonify({"code": 500, "msg": str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# 获取导入详情（根据导入ID获取导入的专利数据）
@app.route("/api/import/detail/<int:import_id>", methods=["GET"])
def get_import_detail(import_id):
    try:
        conn = get_conn()
        cursor = conn.cursor()
        # 先获取导入记录信息
        cursor.execute("SELECT file_name, domain_id FROM import_history WHERE id = %s", (import_id,))
        import_info = cursor.fetchone()
        if not import_info:
            return jsonify({"code": 404, "msg": "导入记录不存在"})
        
        file_name = import_info[0]
        domain_id = import_info[1]
        
        # 查询该导入的专利数据
        cursor.execute("""
            SELECT 
                id, 公开公告号, 发明名称, 公开公告日, 申请专利权人, 发明人, 摘要, IPC分类号
            FROM patents 
            WHERE file_name = %s AND technology_domain_id = %s
        """, (file_name, domain_id))
        patents = []
        for row in cursor.fetchall():
            patents.append({
                "id": row[0],
                "公开公告号": row[1],
                "发明名称": row[2],
                "公开公告日": row[3],
                "申请专利权人": row[4],
                "发明人": row[5],
                "摘要": row[6],
                "IPC分类号": row[7]
            })
        
        return jsonify({
            "code": 200,
            "data": {
                "import_id": import_id,
                "file_name": file_name,
                "domain_id": domain_id,
                "patents": patents
            }
        })
    except Exception as e:
        print(f"❌ 获取导入详情失败: {str(e)}")
        return jsonify({"code": 500, "msg": str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# 删除导入记录（同时删除相关的专利数据）
@app.route("/api/import/delete/<int:import_id>", methods=["DELETE"])
def delete_import_record(import_id):
    try:
        conn = get_conn()
        cursor = conn.cursor()
        # 先获取导入记录信息
        cursor.execute("SELECT file_name, domain_id, count FROM import_history WHERE id = %s", (import_id,))
        import_info = cursor.fetchone()
        if not import_info:
            return jsonify({"code": 404, "msg": "导入记录不存在"})
        
        file_name = import_info[0]
        domain_id = import_info[1]
        patent_count = import_info[2]
        
        # 开始事务
        conn.begin()
        
        # 删除相关的专利数据
        cursor.execute("DELETE FROM patents WHERE file_name = %s AND technology_domain_id = %s", (file_name, domain_id))
        deleted_count = cursor.rowcount
        
        # 删除导入记录
        cursor.execute("DELETE FROM import_history WHERE id = %s", (import_id,))
        
        # 提交事务
        conn.commit()
        
        return jsonify({
            "code": 200,
            "msg": f"删除成功：删除了 {deleted_count} 条专利数据和 1 条导入记录",
            "data": {"deleted_count": deleted_count}
        })
    except Exception as e:
        print(f"删除导入记录失败: {str(e)}")
        if conn:
            conn.rollback()
        return jsonify({"code": 500, "msg": str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# 单个专利导入API
@app.route("/api/import/single", methods=["POST"])
def import_single_patent():
    try:
        data = request.json
        publication_number = data.get("publication_number").strip()
        title = data.get("title").strip()
        technology_domain = data.get("technology_domain")
        publication_date = data.get("publication_date")
        applicant = data.get("applicant", "").strip()
        abstract = data.get("abstract", "").strip()
        citation = data.get("citation", "").strip()
        
        # 验证必填字段
        if not publication_number or not title or not technology_domain:
            return jsonify({"code": 400, "msg": "专利号、专利名称和技术领域为必填字段"})
        
        conn = get_conn()
        cursor = conn.cursor()
        
        # 查重：已存在则跳过
        cursor.execute("SELECT id FROM patents WHERE 公开公告号 = %s", (publication_number,))
        if cursor.fetchone():
            return jsonify({"code": 400, "msg": "该专利号已存在"})
        
        # 插入专利
        cursor.execute("""
            INSERT INTO patents (
                公开公告号, 发明名称, 公开公告日, 申请专利权人, 发明人, 
                摘要, IPC分类号, 引证, technology_domain_id, file_name
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            publication_number,
            title,
            publication_date,
            applicant,
            "",  # 发明人，前端未提供
            abstract,
            "",  # IPC分类号，前端未提供
            citation,
            technology_domain,
            "single_import"
        ))
        
        # 记录导入历史
        cursor.execute("""
            INSERT INTO import_history (file_name, count, type, create_time, domain_id)
            VALUES (%s, %s, %s, NOW(), %s)
        """, ("single_import", 1, "single", technology_domain))
        
        conn.commit()
        return jsonify({
            "code": 200,
            "msg": "单个专利导入成功",
            "data": {"patent_count": 1}
        })
    except Exception as e:
        print(f"单个专利导入失败: {str(e)}")
        if conn:
            conn.rollback()
        return jsonify({"code": 500, "msg": str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    init_import_history_table()
    app.run(host="127.0.0.1", port=5001, debug=True)