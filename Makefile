SHELL		= /bin/bash
DESTDIR		?=
package		= ui-helpers
version		= 0.1.1
revision	= 1
prefix		= ~/.local
bindir		= $(prefix)/bin
datadir		= $(prefix)/share/systemd/user

.PHONY: install-tools
install-tools:
	install -m755 tools/wakeup $(DESTDIR)$(bindir)/

.PHONY: install-polybar
install-polybar:
	install -m755 polybar/polybar-status.py $(DESTDIR)$(bindir)/polybar-status
	install -m755 polybar/polybar-sysmon.py $(DESTDIR)$(bindir)/polybar-sysmon

.PHONY: install
install:
	install -d $(DESTDIR)$(bindir)
	install -m755 bin/volume-notifier $(DESTDIR)$(bindir)/
	install -m755 bin/ui-statuses.py $(DESTDIR)$(bindir)/ui-statuses
	install -m755 bin/ui-list-statuses $(DESTDIR)$(bindir)/
	install -d $(DESTDIR)$(datadir)
	install -m644 systemd/user/ui-statuses.service $(DESTDIR)$(datadir)/
	systemctl --user daemon-reload


.PHONY: uninstall-tools
uninstall-tools:
	rm -f $(DESTDIR)$(bindir)wakeup/

.PHONY: uninstall-polybar
uninstall-polybar:
	rm -f $(DESTDIR)$(bindir)/polybar-status
	rm -f $(DESTDIR)$(bindir)/polybar-sysmon

.PHONY: uninstall
uninstall:
	rm -f $(DESTDIR)$(bindir)/volume-notifier
	rm -f $(DESTDIR)$(bindir)/ui-statuses
	rm -f $(DESTDIR)$(bindir)/ui-list-statuses
	rm -f $(DESTDIR)$(datadir)/ui-statuses.service
	systemctl --user daemon-reload

