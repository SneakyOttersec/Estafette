APP_VERSION ?= 0.1.0-beta.13
PUBLIC_ORIGIN ?= https://sneakyottersec.github.io/Estafette
RCC ?= rcc
BUILD := remarkable/build
PACKAGE_ROOT := $(BUILD)/package-root
APP_BUNDLE := $(PACKAGE_ROOT)/estafette
OVERLAY := $(BUILD)/site-overlay

.PHONY: remarkable-app remarkable-package remarkable-overlay test clean

remarkable-app:
	rm -rf $(PACKAGE_ROOT)
	mkdir -p $(APP_BUNDLE)/backend
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -C remarkable/backend -trimpath -ldflags='-s -w -buildid=' -o ../$(notdir $(BUILD))/package-root/estafette/backend/entry ./cmd/entry
	cp remarkable/app/manifest.json remarkable/app/icon.png $(APP_BUNDLE)/
	cd remarkable/app && $(RCC) --binary -o ../build/package-root/estafette/resources.rcc application.qrc
	chmod 755 $(APP_BUNDLE)/backend/entry

remarkable-package: remarkable-app
	mkdir -p $(PACKAGE_ROOT)/installer/shortcut $(PACKAGE_ROOT)/installer/compat
	cd remarkable/shortcut && $(RCC) --binary -o ../build/package-root/installer/shortcut/estafette-shortcut.rcc application.qrc
	cp remarkable/shortcut/estafette-sidebar-3.28.qmd $(PACKAGE_ROOT)/installer/shortcut/
	cp remarkable/installers/device-install.sh remarkable/installers/advanced-device-install.sh $(PACKAGE_ROOT)/installer/
	cp remarkable/tools/patch_appload_3_28.py $(PACKAGE_ROOT)/installer/
	cp remarkable/compat/*.qmd $(PACKAGE_ROOT)/installer/compat/
	chmod 755 $(PACKAGE_ROOT)/installer/*.sh $(PACKAGE_ROOT)/installer/*.py

remarkable-overlay: remarkable-package
	rm -rf $(OVERLAY)
	python src/package_remarkable_app.py --bundle $(APP_BUNDLE) --overlay $(OVERLAY) --version $(APP_VERSION) --origin $(PUBLIC_ORIGIN)
	cp site/remarkable/install-safe.sh site/remarkable/install-advanced.sh $(OVERLAY)/remarkable/

test:
	PYTHONPATH=src:backend pytest -q
	go test -C remarkable/backend ./...
	node remarkable/tests/test_qml_logic.js remarkable/app/ui/logic.js
	sh -n site/remarkable/install-safe.sh site/remarkable/install-advanced.sh remarkable/installers/*.sh

clean:
	rm -rf remarkable/build
