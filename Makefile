venv:
	virtualenv -p python3 venv
	venv/bin/pip3 install -r requirements.txt

clean:
	rm -rf venv/

test:
	PYTHONPATH=. venv/bin/py.test -vs tests/

test_%:
	PYTHONPATH=. venv/bin/py.test tests -x -k $@ -vv -s

docker:
	docker build -t steinnes/flux:latest .

start_docker:
	docker run -d -p 4042:4042 -v ~/flux:/data -e FLUX_ROOT=/data -e FLUX_HOST=0.0.0.0 steinnes/flux:latest
