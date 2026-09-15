package app

import (
	"testing"

	"cosmossdk.io/log/v2"
	dbm "github.com/cosmos/cosmos-db"
	sdk "github.com/cosmos/cosmos-sdk/types"
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	"github.com/spf13/viper"
)

func testApp(t *testing.T) *App {
	t.Helper()
	opts := viper.New()
	opts.Set("home", t.TempDir())
	app := New(log.NewNopLogger(), dbm.NewMemDB(), true, opts)
	t.Cleanup(func() { _ = app.Close() })
	return app
}

func TestNativeFeesDuringBlockExecution(t *testing.T) {
	app := testApp(t)
	for _, tc := range []struct {
		name  string
		fees  sdk.Coins
		valid bool
	}{
		{"native-minimum", sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1000)), true},
		{"native-above-minimum", sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 1001)), true},
		{"underpayment", sdk.NewCoins(sdk.NewInt64Coin(BaseDenom, 999)), false},
		{"no-fee", sdk.NewCoins(), false},
		{"external-currency", sdk.NewCoins(sdk.NewInt64Coin("stake", 100000)), false},
		{"mixed-currencies", sdk.NewCoins(sdk.NewInt64Coin("stake", 1000), sdk.NewInt64Coin(BaseDenom, 1000)), false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			builder := app.TxConfig().NewTxBuilder()
			builder.SetFeeAmount(tc.fees)
			called := false
			next := func(ctx sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) { called = true; return ctx, nil }
			_, err := nativeFeeAnte(next)(sdk.Context{}.WithBlockHeight(1), builder.GetTx(), false)
			if (err == nil) != tc.valid || called != tc.valid {
				t.Fatalf("valid=%v next=%v err=%v", tc.valid, called, err)
			}
		})
	}
}

func TestGenesisAndSimulationDoNotRequireFees(t *testing.T) {
	app := testApp(t)
	for _, tc := range []struct {
		height   int64
		simulate bool
	}{{0, false}, {1, true}} {
		called := false
		next := func(ctx sdk.Context, _ sdk.Tx, _ bool) (sdk.Context, error) { called = true; return ctx, nil }
		_, err := nativeFeeAnte(next)(sdk.Context{}.WithBlockHeight(tc.height), app.TxConfig().NewTxBuilder().GetTx(), tc.simulate)
		if err != nil || !called {
			t.Fatalf("genesis/simulation rejected: %v", err)
		}
	}
}

func TestNoMintAuthorityOrUnexpectedModules(t *testing.T) {
	app := testApp(t)
	expected := map[string]bool{"auth": true, "bank": true, "staking": true, "distribution": true,
		"slashing": true, "evidence": true, "consensus": true, "genutil": true, "gov": true, "upgrade": true}
	if len(app.ModuleManager.Modules) != len(expected) {
		t.Fatalf("unexpected module count: %d", len(app.ModuleManager.Modules))
	}
	for name := range app.ModuleManager.Modules {
		if !expected[name] {
			t.Fatalf("unexpected module: %s", name)
		}
	}
	for name, permissions := range GetMaccPerms() {
		for _, permission := range permissions {
			if permission == authtypes.Minter {
				t.Fatalf("module %s has mint authority", name)
			}
		}
	}
	if _, exists := app.DefaultGenesis()["mint"]; exists {
		t.Fatal("mint module was registered")
	}
	address, err := app.AccountKeeper.AddressCodec().BytesToString(make([]byte, 20))
	if err != nil || len(address) < len(AccountPrefix) || address[:len(AccountPrefix)] != AccountPrefix {
		t.Fatalf("wrong native address prefix: %s %v", address, err)
	}
}
