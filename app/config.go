package app

import (
	"os"
	"path/filepath"

	sdk "github.com/cosmos/cosmos-sdk/types"
	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
)

const (
	AccountPrefix         = "luxar"
	BaseDenom             = "uluxar"
	DisplayDenom          = "luxar"
	DisplayExponent       = 6
	MinimumFee      int64 = 1000
)

func init() {
	home, err := os.UserHomeDir()
	if err != nil {
		panic(err)
	}
	DefaultNodeHome = filepath.Join(home, ".luxartium")
	cfg := sdk.GetConfig()
	cfg.SetBech32PrefixForAccount(AccountPrefix, AccountPrefix+"pub")
	cfg.SetBech32PrefixForValidator(AccountPrefix+"valoper", AccountPrefix+"valoperpub")
	cfg.SetBech32PrefixForConsensusNode(AccountPrefix+"valcons", AccountPrefix+"valconspub")
}

// Fees are checked during block execution as well as mempool admission. Genesis
// validator transactions and gas simulation do not pay a transaction fee.
func nativeFeeAnte(next sdk.AnteHandler) sdk.AnteHandler {
	return func(ctx sdk.Context, tx sdk.Tx, simulate bool) (sdk.Context, error) {
		if ctx.BlockHeight() > 0 && !simulate {
			feeTx, ok := tx.(sdk.FeeTx)
			if !ok {
				return ctx, sdkerrors.ErrTxDecode.Wrap("transaction must expose a fee")
			}
			fees := feeTx.GetFee()
			if len(fees) != 1 || fees[0].Denom != BaseDenom || fees[0].Amount.LT(sdk.NewInt64Coin(BaseDenom, MinimumFee).Amount) {
				return ctx, sdkerrors.ErrInsufficientFee.Wrap("minimum fee is 1000uluxar; only native Luxartium is accepted")
			}
		}
		return next(ctx, tx, simulate)
	}
}
