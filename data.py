# advanced_patent_import.py
import os
import re
from datetime import datetime

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text

class AdvancedPatentImporter:
    def __init__(self, db_config):
        self.engine = create_engine(
            f"mysql+pymysql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['database']}"
        )
        self.domain_cache = {}
        self.applicant_cache = {}
        self.inventor_cache = {}
        self.ipc_cache = {}
        
    def get_technology_domain_id(self, domain_name):
        """获取技术领域ID"""
        if domain_name not in self.domain_cache:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT id FROM technology_domains WHERE domain_name = :name"),
                    {'name': domain_name}
                ).fetchone()
                if result:
                    self.domain_cache[domain_name] = result[0]
                else:
                    print(f"警告: 技术领域 {domain_name} 不存在")
                    return None
        return self.domain_cache[domain_name]
    
    def parse_applicant_type(self, applicant_name):
        """智能判断申请人类型"""
        if not applicant_name or pd.isna(applicant_name) or applicant_name == '':
            return '其他'
        
        applicant_str = str(applicant_name)
        # 企业特征词
        company_indicators = ['公司', '集团', '有限', '股份', '厂', '企业', '科技', '技术', '电子', '通信']
        # 高校特征词
        university_indicators = ['大学', '学院', '学校', '研究所', '研究院', '实验室']
        # 科研机构特征词
        research_indicators = ['科学院', '研究中心', '设计院', '工程院']
        
        if any(indicator in applicant_str for indicator in university_indicators):
            return '高校'
        elif any(indicator in applicant_str for indicator in research_indicators):
            return '科研机构'
        elif any(indicator in applicant_str for indicator in company_indicators):
            return '企业'
        elif '个人' in applicant_str or len(applicant_str) < 10:
            return '个人'
        else:
            return '其他'
    
    def import_patent_data(self, data_dir=None):
        # 第一步：重新定义正确的data路径（核心修改）
        # 获取当前代码文件所在的绝对目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # 如果没有传入 data_dir，则使用代码目录下的 data 文件夹
        if not data_dir:
            real_data_dir = os.path.join(script_dir, 'data')
        else:
            # 若传入相对路径，则基于脚本目录构建绝对路径；若传入绝对路径则直接使用
            real_data_dir = data_dir if os.path.isabs(data_dir) else os.path.join(script_dir, data_dir)

        # 第二步：增加路径检查，不存在则自动创建（可选但推荐）
        if not os.path.exists(real_data_dir):
            os.makedirs(real_data_dir)
            print(f"提示：自动创建data文件夹 -> {real_data_dir}")
            print("请将Excel专利数据文件放入该文件夹后重新运行！")
            return

        # 第三步：用正确的路径读取文件（替换原来的os.listdir(data_dir)）
        excel_files = [f for f in os.listdir(real_data_dir) if f.endswith(('.xlsx', '.xls'))]

        if not excel_files:
            print("未找到Excel文件")
            return

        total_records = 0
        success_files = 0

        for file_name in excel_files:
            try:
                print(f"\n处理文件: {file_name}")
                file_path = os.path.join(real_data_dir, file_name)

                # 从文件名提取技术领域
                domain_name = self.extract_domain_from_filename(file_name)
                domain_id = self.get_technology_domain_id(domain_name)

                if not domain_id:
                    print(f"警告: 无法找到技术领域 {domain_name} 的ID，跳过此文件")
                    continue

                # 读取Excel文件
                df = pd.read_excel(file_path, sheet_name='Sheet1')
                print(f"读取到 {len(df)} 条记录")

                # 数据清洗和转换
                df_cleaned = self.clean_patent_data(df, domain_id)

                # 导入数据库
                record_count = self.import_to_database(df_cleaned, domain_id)
                total_records += record_count
                success_files += 1
                print(f"成功导入 {record_count} 条记录")

            except Exception as e:
                print(f"处理文件 {file_name} 时出错: {e}")
                continue

        print(f"\n导入完成! 成功处理 {success_files}/{len(excel_files)} 个文件, 总计 {total_records} 条记录")
    
    def clean_patent_data(self, df, domain_id):
        """数据清洗"""
        df_clean = df.copy()
        
        # 重命名列以匹配数据库字段名
        column_mapping = {
            '公开（公告）号': '公开公告号',
            '公开（公告）日': '公开公告日',
            '申请（专利权）人': '申请专利权人',
            '发明名称': '发明名称',
            '摘要': '摘要',
            '引证': '引证',
            'IPC分类号': 'IPC分类号'
        }
        
        # 应用列名映射
        df_clean = df_clean.rename(columns=column_mapping)
        
        # 处理文本字段，确保不为NaN
        text_columns = ['公开公告号', '公开公告日', '申请专利权人', '发明名称', '摘要', '引证', 'IPC分类号']
        for col in text_columns:
            if col in df_clean.columns:
                df_clean[col] = df_clean[col].fillna('').astype(str)
            else:
                print(f"警告: 列 {col} 不存在于数据中")
                df_clean[col] = ''
        
        # 添加技术领域ID
        df_clean['technology_domain_id'] = domain_id
        
        return df_clean
    
    def extract_domain_from_filename(self, filename):
        """从文件名提取技术领域"""
        domain_map = {
            '人工智能': ['人工智能', 'AI', '智能'],
            '大数据': ['大数据', '数据挖掘', '数据分析'],
            '物联网': ['物联网', 'IoT'],
            '区块链': ['区块链', 'Blockchain'],
            '5G': ['5G', '第五代'],
            '量子计算': ['量子计算', '量子'],
            '云计算': ['云计算', '云服务']
        }
        
        filename_lower = filename.lower()
        for domain, keywords in domain_map.items():
            if any(keyword.lower() in filename_lower for keyword in keywords):
                return domain
        
        # 如果无法识别，尝试从文件名直接提取
        if '区块链' in filename:
            return '区块链'
        elif '人工智能' in filename or 'AI' in filename:
            return '人工智能'
        elif '物联网' in filename or 'IoT' in filename:
            return '物联网'
        elif '大数据' in filename:
            return '大数据'
        elif '5G' in filename:
            return '5G'
        elif '量子' in filename:
            return '量子计算'
        elif '云' in filename:
            return '云计算'
        else:
            print(f"警告: 无法从文件名 {filename} 识别技术领域，使用默认值")
            return '其他'
    
    def import_to_database(self, df, domain_id):
        """将数据导入数据库"""
        record_count = 0
        
        with self.engine.connect() as conn:
            trans = conn.begin()
            try:
                for index, row in df.iterrows():
                    # 插入专利基本信息
                    patent_id = self.insert_patent(conn, row, domain_id)
                    if patent_id:
                        # 处理申请人（多值字段，分号分隔）
                        if row.get('申请专利权人', '').strip():
                            self.process_applicants(conn, patent_id, row['申请专利权人'])
                        
                        # 处理发明人（多值字段，分号分隔）
                        if row.get('发明人', '').strip():
                            self.process_inventors(conn, patent_id, row['发明人'])
                        
                        # 处理IPC分类（多值字段，分号分隔）
                        if row.get('IPC分类号', '').strip():
                            self.process_ipcs(conn, patent_id, row['IPC分类号'])
                        
                        # 处理引证数据（仅统一分隔符，不修改专利号）
                        if row.get('引证', '').strip():
                            self.process_citations(conn, patent_id, row['引证'])
                        
                        record_count += 1
                        
                        if record_count % 100 == 0:
                            print(f"已处理 {record_count} 条记录...")
                
                trans.commit()
                print(f"成功提交事务，导入 {record_count} 条记录")
                
            except Exception as e:
                print(f"导入错误: {e}")
                trans.rollback()
                raise
        
        return record_count
    
    def insert_patent(self, conn, row, domain_id):
        """插入专利记录 - 适配新的表结构"""
        try:
            # 使用新的字段名和表结构
            patent_query = text("""
                INSERT INTO patents (
                    公开公告号, 公开公告日, IPC分类号, 申请专利权人,
                    发明人, 发明名称, 摘要, 引证, technology_domain_id
                ) VALUES (
                    :pub_num, :pub_date, :ipc, :applicant,
                    :inventor, :title, :abstract, :citation, :domain_id
                )
            """)
            
            result = conn.execute(patent_query, {
                'pub_num': row.get('公开公告号', ''),
                'pub_date': row.get('公开公告日', ''),
                'ipc': row.get('IPC分类号', ''),
                'applicant': row.get('申请专利权人', ''),
                'inventor': row.get('发明人', ''),
                'title': row.get('发明名称', ''),
                'abstract': row.get('摘要', ''),
                'citation': row.get('引证', ''),
                'domain_id': domain_id
            })
            
            return result.lastrowid
            
        except Exception as e:
            print(f"插入专利错误: {e}")
            print(f"错误数据: {row.get('公开公告号', '未知')}")
            return None

    def process_applicants(self, conn, patent_id, applicants_str):
        """处理申请人数据 - 多值字段解析"""
        try:
            # 按分号分割多个申请人
            applicants = [app.strip() for app in str(applicants_str).split(';') if app.strip()]
            
            for seq, app_name in enumerate(applicants, 1):
                if not app_name or app_name == '':
                    continue
                    
                if app_name not in self.applicant_cache:
                    # 智能判断申请人类型
                    app_type = self.parse_applicant_type(app_name)
                    
                    # 插入申请人
                    try:
                        app_result = conn.execute(
                            text("INSERT IGNORE INTO applicants (name, applicant_type) VALUES (:name, :type)"),
                            {'name': app_name, 'type': app_type}
                        )
                        
                        # 获取申请人ID
                        app_id_result = conn.execute(
                            text("SELECT id FROM applicants WHERE name = :name"),
                            {'name': app_name}
                        ).fetchone()
                        
                        if app_id_result:
                            self.applicant_cache[app_name] = app_id_result[0]
                        else:
                            continue
                    except Exception as e:
                        print(f"插入申请人错误 {app_name}: {e}")
                        continue
                
                # 插入关联关系
                if self.applicant_cache.get(app_name):
                    try:
                        conn.execute(
                            text("INSERT IGNORE INTO patent_applicant (patent_id, applicant_id, applicant_sequence) VALUES (:pid, :aid, :seq)"),
                            {'pid': patent_id, 'aid': self.applicant_cache[app_name], 'seq': seq}
                        )
                    except Exception as e:
                        print(f"插入申请人关联错误: {e}")
        except Exception as e:
            print(f"处理申请人数据错误: {e}")

    def process_inventors(self, conn, patent_id, inventors_str):
        """处理发明人数据 - 多值字段解析"""
        try:
            # 按分号分割多个发明人
            inventors = [inv.strip() for inv in str(inventors_str).split(';') if inv.strip()]
            
            for seq, inv_name in enumerate(inventors, 1):
                if not inv_name or inv_name == '':
                    continue
                    
                if inv_name not in self.inventor_cache:
                    # 插入发明人
                    try:
                        conn.execute(
                            text("INSERT IGNORE INTO inventors (name) VALUES (:name)"),
                            {'name': inv_name}
                        )
                        
                        # 获取发明人ID
                        inv_id_result = conn.execute(
                            text("SELECT id FROM inventors WHERE name = :name"),
                            {'name': inv_name}
                        ).fetchone()
                        
                        if inv_id_result:
                            self.inventor_cache[inv_name] = inv_id_result[0]
                        else:
                            continue
                    except Exception as e:
                        print(f"插入发明人错误 {inv_name}: {e}")
                        continue
                
                # 插入关联关系
                if self.inventor_cache.get(inv_name):
                    try:
                        conn.execute(
                            text("INSERT IGNORE INTO patent_inventor (patent_id, inventor_id, inventor_sequence) VALUES (:pid, :iid, :seq)"),
                            {'pid': patent_id, 'iid': self.inventor_cache[inv_name], 'seq': seq}
                        )
                    except Exception as e:
                        print(f"插入发明人关联错误: {e}")
        except Exception as e:
            print(f"处理发明人数据错误: {e}")

    def process_ipcs(self, conn, patent_id, ipcs_str):
        """处理IPC分类数据 - 多值字段解析"""
        try:
            # 按分号分割多个IPC分类
            ipcs = [ipc.strip() for ipc in str(ipcs_str).split(';') if ipc.strip()]
            
            for ipc_code in ipcs:
                if not ipc_code or ipc_code == '':
                    continue
                    
                if ipc_code not in self.ipc_cache:
                    # 插入IPC分类
                    try:
                        conn.execute(
                            text("INSERT IGNORE INTO ipc_classes (ipc_code) VALUES (:code)"),
                            {'code': ipc_code}
                        )
                        
                        # 获取IPC ID
                        ipc_id_result = conn.execute(
                            text("SELECT id FROM ipc_classes WHERE ipc_code = :code"),
                            {'code': ipc_code}
                        ).fetchone()
                        
                        if ipc_id_result:
                            self.ipc_cache[ipc_code] = ipc_id_result[0]
                        else:
                            continue
                    except Exception as e:
                        print(f"插入IPC分类错误 {ipc_code}: {e}")
                        continue
                
                # 插入关联关系（第一个IPC作为主分类）
                if self.ipc_cache.get(ipc_code):
                    is_main = ipcs.index(ipc_code) == 0
                    try:
                        conn.execute(
                            text("INSERT IGNORE INTO patent_ipc (patent_id, ipc_class_id, main_ipc) VALUES (:pid, :ipcid, :main)"),
                            {'pid': patent_id, 'ipcid': self.ipc_cache[ipc_code], 'main': is_main}
                        )
                    except Exception as e:
                        print(f"插入IPC关联错误: {e}")
        except Exception as e:
            print(f"处理IPC数据错误: {e}")

    def process_citations(self, conn, patent_id, citations_str):
        """处理引证数据 - 仅统一分隔符为空格，保留完整专利号（含前缀）、保留重复项"""
        try:
            # 仅做分隔符替换：将全角/半角逗号、顿号、分号统一替换为空格
            citations_str = str(citations_str)
            # 替换所有目标分隔符为空格
            separators = ['、', '，', ';', ',', '|', '\t', '\n', '\r']
            for sep in separators:
                citations_str = citations_str.replace(sep, ' ')
            
            # 按空格分割（保留空值过滤，仅过滤纯空白的项，不过滤重复专利号）
            citations = [cit.strip() for cit in citations_str.split(' ') if cit.strip()]
            
            # 为每个引证创建记录（保留重复项）
            for seq, cited_patent_id in enumerate(citations, 1):
                if not cited_patent_id:
                    continue
                
                try:
                    # 直接插入引证记录，不检查被引证专利是否存在
                    # 注意：这里假设cited_patent_id字段是字符串类型
                    # 如果数据库表结构中cited_patent_id是int类型，需要修改表结构
                    conn.execute(
                        text("INSERT IGNORE INTO patent_citations (citing_patent_id, cited_patent_id, citation_type) VALUES (:citing_id, :cited_id, '直接引用')"),
                        {'citing_id': patent_id, 'cited_id': cited_patent_id}
                    )
                except Exception as e:
                    print(f"插入引证错误 {cited_patent_id}: {e}")
                    continue
        except Exception as e:
            print(f"处理引证数据错误: {e}")

    def validate_import(self):
        """验证导入结果"""
        with self.engine.connect() as conn:
            # 统计各表记录数
            tables = ['patents', 'applicants', 'inventors', 'ipc_classes', 
                     'patent_applicant', 'patent_inventor', 'patent_ipc', 'patent_citations']
            
            print("\n导入验证结果:")
            for table in tables:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                print(f"{table}: {count} 条记录")
            
            # 按技术领域统计专利数
            domain_stats = conn.execute(text("""
                SELECT td.domain_name, COUNT(p.id) as patent_count
                FROM technology_domains td
                LEFT JOIN patents p ON td.id = p.technology_domain_id
                GROUP BY td.id, td.domain_name
                ORDER BY patent_count DESC
            """)).fetchall()
            
            print("\n按技术领域统计:")
            for domain, count in domain_stats:
                print(f"{domain}: {count} 件专利")

# 使用示例
if __name__ == "__main__":
    db_config = {
        'host': 'localhost',
        'port': 3306,
        'user': 'root',
        'password': '123456',
        'database': 'patent_analysis_platform'
    }
    
    importer = AdvancedPatentImporter(db_config)
    
    # 导入数据
    importer.import_patent_data('data')
    
    # 验证导入结果
    importer.validate_import()