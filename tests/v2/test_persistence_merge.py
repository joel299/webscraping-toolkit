from packages.persistence.lead_repository import LeadRepository

def test_update_preserves_commercial_fields():
    db={'id':'x','place_name':'Old','source_category':'clinica','source_city':'CG','source_state':'MS','lead_status':'enviado','pipeline_stage':'followup','responded':True,'converted':False}
    def get(_): return dict(db) if db else None
    def insert(row): db.update(row)
    def update(_,row): db.update(row)
    result=LeadRepository(get,insert,update).upsert('x',{'id':'x','place_name':'New','source_category':'clinica','source_city':'CG','source_state':'MS','lead_status':'new','responded':False})
    assert result.verified and result.action=='updated'
    assert db['lead_status']=='enviado' and db['pipeline_stage']=='followup' and db['responded'] is True

def test_insert_requires_fresh_readback():
    db={}
    def get(_): return dict(db) if db else None
    def insert(row): db.update(row)
    def update(_,row): db.update(row)
    result=LeadRepository(get,insert,update).upsert('x',{'id':'x','place_name':'New','source_category':'clinica','source_city':'CG','source_state':'MS'})
    assert result.verified and result.action=='inserted'
