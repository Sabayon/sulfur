PKGDIR = /$(LIBDIR)/entropy/sulfur/sulfur
REPOMANDIR = /$(LIBDIR)/entropy/repoman/repoman

all:

clean:
	rm -fv sulfur/*.pyc sulfur/*.pyo sulfur/*~ sulfur/*.bak sulfur/*.gladep

install:
	mkdir -p $(DESTDIR)/$(PKGDIR)
	mkdir -p $(DESTDIR)/$(REPOMANDIR)

	install -m755 sulfur_client.py $(DESTDIR)/$(PKGDIR)/..
	install -m644 sulfur/*.py $(DESTDIR)/$(PKGDIR)/.
	install -m644 sulfur/revision $(DESTDIR)/$(PKGDIR)/.
	install -m644 sulfur/*.glade $(DESTDIR)/$(PKGDIR)/.
