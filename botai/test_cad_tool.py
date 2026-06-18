import urllib.request
import json

def test_cad():
    print("Testing CAD formats endpoint...")
    try:
        req = urllib.request.urlopen("http://localhost:3000/api/cad/formats")
        data = json.loads(req.read().decode('utf-8'))
        assert data['success'] is True
        print("Formats API OK!")
    except Exception as e:
        print(f"Formats API FAILED: {e}")
        return False

    print("Testing CAD generation endpoint...")
    post_data = {
        "filename": "test",
        "claude_response": "cube([100, 100, 100]);",
        "format": "scad"
    }
    req_body = json.dumps(post_data).encode('utf-8')
    try:
        req = urllib.request.Request(
            "http://localhost:3000/api/cad/generate",
            data=req_body,
            headers={'Content-Type': 'application/json'}
        )
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read().decode('utf-8'))
        assert result['success'] is True
        file_id = result['file_id']
        display_name = result['display_name']
        print(f"CAD generation OK! File ID: {file_id}, Name: {display_name}")
    except Exception as e:
        print(f"CAD generation FAILED: {e}")
        return False

    print("Testing CAD download endpoint...")
    try:
        req = urllib.request.urlopen(f"http://localhost:3000/api/cad/download/{file_id}")
        content = req.read().decode('utf-8')
        assert "cube([100, 100, 100]);" in content
        print("CAD download OK! File contents verified.")
    except Exception as e:
        print(f"CAD download FAILED: {e}")
        return False

    print("Testing 3DXML generation endpoint...")
    post_data_xml = {
        "filename": "model3d",
        "claude_response": "<3DXML><ProductStructure></ProductStructure></3DXML>",
        "format": "3dxml"
    }
    req_body_xml = json.dumps(post_data_xml).encode('utf-8')
    try:
        req = urllib.request.Request(
            "http://localhost:3000/api/cad/generate",
            data=req_body_xml,
            headers={'Content-Type': 'application/json'}
        )
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read().decode('utf-8'))
        assert result['success'] is True
        file_id_xml = result['file_id']
        display_name_xml = result['display_name']
        print(f"3DXML generation OK! File ID: {file_id_xml}, Name: {display_name_xml}")
    except Exception as e:
        print(f"3DXML generation FAILED: {e}")
        return False

    print("Testing 3DXML download endpoint...")
    try:
        req = urllib.request.urlopen(f"http://localhost:3000/api/cad/download/{file_id_xml}")
        content = req.read().decode('utf-8')
        assert "<3DXML>" in content
        print("3DXML download OK! File contents verified.")
    except Exception as e:
        print(f"3DXML download FAILED: {e}")
        return False

    print("ALL TESTS PASSED SUCCESSFULLY! (OK)")
    return True

if __name__ == "__main__":
    test_cad()
