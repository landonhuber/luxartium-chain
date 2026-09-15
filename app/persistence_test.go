package app

import (
	"testing"

	"cosmossdk.io/log/v2"
	dbm "github.com/cosmos/cosmos-db"
	store "github.com/cosmos/cosmos-sdk/store/v2"
	storetypes "github.com/cosmos/cosmos-sdk/store/v2/types"
)

// This must use the on-disk database. MemDB hides the LevelDB empty-value bug
// that breaks queries as soon as a module has an empty committed IAVL root.
func TestCommittedEmptyStoreCanBeQueriedAndReopened(t *testing.T) {
	dir := t.TempDir()
	db, err := dbm.NewDB("chain", dbm.GoLevelDBBackend, dir)
	if err != nil {
		t.Fatal(err)
	}
	if err = db.Set([]byte("empty-value"), []byte{}); err != nil {
		t.Fatal(err)
	}
	value, err := db.Get([]byte("empty-value"))
	if err != nil || value == nil {
		t.Fatalf("present empty value became absent: %v", err)
	}
	populated := storetypes.NewKVStoreKey("populated")
	empty := storetypes.NewKVStoreKey("empty")
	ms := store.NewCommitMultiStore(db, log.NewNopLogger())
	ms.MountStoreWithDB(populated, storetypes.StoreTypeIAVL, nil)
	ms.MountStoreWithDB(empty, storetypes.StoreTypeIAVL, nil)
	if err = ms.LoadLatestVersion(); err != nil {
		t.Fatal(err)
	}
	ms.GetKVStore(populated).Set([]byte("balance"), []byte("1000"))
	version := ms.Commit().Version
	queried, err := ms.CacheMultiStoreWithVersion(version)
	if err != nil {
		t.Fatal(err)
	}
	if string(queried.GetKVStore(populated).Get([]byte("balance"))) != "1000" {
		t.Fatal("committed balance missing")
	}
	if err = db.Close(); err != nil {
		t.Fatal(err)
	}
	db, err = dbm.NewDB("chain", dbm.GoLevelDBBackend, dir)
	if err != nil {
		t.Fatal(err)
	}
	reopened := store.NewCommitMultiStore(db, log.NewNopLogger())
	t.Cleanup(func() { _ = db.Close() })
	reopened.MountStoreWithDB(populated, storetypes.StoreTypeIAVL, nil)
	reopened.MountStoreWithDB(empty, storetypes.StoreTypeIAVL, nil)
	if err = reopened.LoadLatestVersion(); err != nil {
		t.Fatal(err)
	}
	queried, err = reopened.CacheMultiStoreWithVersion(version)
	if err != nil {
		t.Fatal(err)
	}
	if string(queried.GetKVStore(populated).Get([]byte("balance"))) != "1000" {
		t.Fatal("reopened balance missing")
	}
}
